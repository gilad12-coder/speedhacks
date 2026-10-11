"""Research must earn facts and risk conclusions from external evidence."""
from househunt.models import Contact, Listing, SearchCriteria, Source
from househunt.research.engine import Rental, Review, auto_call_eligible, parse_rental, validate_review
from househunt.research.web import Page, canonical_url, fetch_page


def target():
    return Listing(source=Source.OTHER, source_id="one", url="https://listings.example.com/unit1",
                   title="Example", address="100 Pine Street Unit 1", beds=2, price=1000,
                   contact=Contact(phone="+12025552222"))


def test_public_page_evidence_rejects_invented_facts_and_negative_must_haves():
    from househunt.collect import passes_filters
    page = Page("https://rentals.example.com/unit1", "A rental", "100 Pine Street Unit 1. Rent $3,200/month. 2 bedrooms. Laundry is shared; no in-unit machines.")
    rental = Rental(url=page.url, is_specific_rental=True, in_requested_city=True,
                    availability="advertised_available", availability_quote="Available now",
                    facts=[{"key":"rent","value":"2500","quote":"Rent $3,200/month."},
                           {"key":"beds","value":"2","quote":"2 bedrooms."},
                           {"key":"phone","value":"+12025552222","quote":"Call 202-555-2222"},
                           {"key":"address","value":"100 Pine Street Unit 1","quote":"100 Pine Street Unit 1."}],
                    requirements=[{"requirement":"in-unit laundry","matched":False,
                                   "quote":"Laundry is shared; no in-unit machines."}])
    criteria = SearchCriteria(city="SF",max_price=4000,must_haves=["in-unit laundry","pets"])
    listing = parse_rental(rental,page,criteria)
    assert listing.price is None and listing.contact is None
    assert listing.beds == 2 and listing.research["availability"] == "unknown"
    assert listing.research["requirements"][1]["matched"] is None
    assert not passes_filters(listing,criteria)[0]


def test_cross_search_does_not_promote_unsupported_or_wrong_unit_claims():
    page = Page("https://manager.example.org/100", "Manager", "100 Pine Street Unit 1. Call 202-555-2222.")
    review = Review(findings=[
        {"kind":"address_corroborated","url":page.url,"quote":"100 Pine Street Unit 1.","explanation":"Address listed","same_unit":True,"supports_finding":True},
        {"kind":"contact_corroborated","url":page.url,"quote":"Call 202-555-2222.","explanation":"Contact listed","same_unit":True,"supports_finding":True},
        {"kind":"rent_conflict","url":page.url,"quote":"Rent $3000","explanation":"Invented","same_unit":True,"supports_finding":True},
        {"kind":"contact_conflict","url":page.url,"quote":"Call 202-555-2222.","explanation":"Wrong unit","same_unit":False,"supports_finding":True},
    ],comparables=[])
    listing = target()
    result = validate_review(review,[page],listing)
    assert result['status'] == 'cross_referenced' and len(result['findings']) == 2
    listing.screening = result
    assert auto_call_eligible(listing)
    # Same-domain copies do not count as independent cross-references.
    listing.url = page.url
    assert validate_review(review,[page],listing)['status'] == 'unconfirmed'
    # Uncited model URLs never earn positive evidence.
    assert validate_review(review,[],target())['status'] == 'unconfirmed'


def test_price_outlier_needs_three_distinct_grounded_comparables():
    listing = target()
    pages, comps = [], []
    for n in range(3):
        address = f"{200+n} Pine Street"
        page = Page(f"https://rentals.example.org/{n}", address, f"{address}. Rent $3,000/month. 2 bedrooms.")
        pages.append(page)
        comps.append({"url":page.url,"address":address,"price":3000,"beds":2,"neighborhood":"Pine",
                      "same_area":True,"price_quote":"Rent $3,000/month.","beds_quote":"2 bedrooms.","address_quote":address})
    report = validate_review(Review(findings=[],comparables=comps[:2]),pages,listing)
    assert report['market']['median_rent'] is None and report['status'] == 'unconfirmed'
    report = validate_review(Review(findings=[],comparables=comps),pages,listing)
    assert report['market']['median_rent'] == 3000 and report['status'] == 'concerns_found'
    assert report['findings'][0]['kind'] == 'price_outlier'
    listing.screening = report
    assert not auto_call_eligible(listing)
    comps[2]['address'] = comps[0]['address']
    report = validate_review(Review(findings=[],comparables=comps),pages,listing)
    assert report['market']['median_rent'] is None


def test_matching_price_ranges_and_platform_warnings_are_not_risk_flags():
    listing = target()
    listing.price = 2830
    page = Page('https://rentals.example.org/one', 'Rental',
                '2 beds $2,825–$3,320. DO NOT wire funds, or buy/rent sight unseen.')
    review = Review(findings=[
        {'kind':'rent_conflict','url':page.url,'quote':'2 beds $2,825–$3,320.',
         'explanation':'Range differs','same_unit':True,'supports_finding':True},
        {'kind':'upfront_payment','url':page.url,'quote':'DO NOT wire funds, or buy/rent sight unseen.',
         'explanation':'Payment warning','same_unit':True,'supports_finding':True},
    ],comparables=[])
    result = validate_review(review,[page],listing)
    assert result['status'] == 'unconfirmed' and not result['findings']


def test_building_price_difference_does_not_claim_same_unit_conflict():
    listing=target()
    listing.address='100 Pine Street'
    page=Page('https://rentals.example.org/one','Rental','100 Pine Street. Rent $9,000/month.')
    review=Review(findings=[{'kind':'rent_conflict','url':page.url,'quote':'Rent $9,000/month.',
        'explanation':'Same unit','same_unit':True,'supports_finding':True}],comparables=[])
    finding=validate_review(review,[page],listing)['findings'][0]
    assert finding['kind']=='price_difference' and finding['same_unit'] is False


def test_dedupe_keeps_different_units_with_same_leasing_phone():
    from househunt.collect import dedupe
    a, b = target(), target()
    a.address = b.address = None
    b.source_id = 'two'
    assert len(dedupe([a,b])) == 2
    a.address, b.address = '100 Pine St Apt 1', '100 Pine St Unit 2'
    assert len(dedupe([a,b])) == 2
    b.address, b.url = '100 Pine St Unit 1', 'https://another.example.com/1'
    assert len(dedupe([a,b])) == 1 and b.url in a.provenance


def test_private_and_credential_urls_cannot_be_fetched(monkeypatch):
    import socket
    for url in ('http://127.0.0.1/', 'http://169.254.169.254/', 'file:///etc/passwd',
                'https://u:secret@example.com', 'http://evil.local/', 'https://example.com:8789/'):
        assert canonical_url(url) == ''
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    assert fetch_page('https://public.example.com') is None


def test_renter_identity_is_used_but_not_sent_to_web_search():
    from househunt.outreach.script import build_instruction
    from househunt.research.provider import public_criteria
    criteria = SearchCriteria(city='SF',max_price=4000,renter_name='Reed',tour_availability=['private calendar detail'])
    prompt = build_instruction(target(),criteria,'Someone Else')
    assert 'Reed' in prompt and 'Someone Else' not in prompt
    assert 'Do not claim to be the renter' in prompt
    assert 'Reed' not in public_criteria(criteria) and 'private calendar detail' not in public_criteria(criteria)


def test_discovery_uses_provider_citations_not_generated_links(monkeypatch):
    import httpx
    from dataclasses import replace
    import househunt.config
    from househunt.research.provider import ask,Links
    monkeypatch.setattr(househunt.config,'settings',replace(househunt.config.settings,openai_api_key='test'))
    body={'status':'completed','output':[
        {'type':'web_search_call','status':'completed'},
        {'type':'message','content':[{'type':'output_text','text':'https://invented.example.com/',
          'annotations':[{'type':'url_citation','url':'https://observed.example.com/rental','title':'Observed'}]}]}]}
    monkeypatch.setattr(httpx,'post',lambda *a,**k:httpx.Response(200,json=body))
    result=ask('find rentals',Links,search=True)
    assert [l.url for l in result.links]==['https://observed.example.com/rental']
