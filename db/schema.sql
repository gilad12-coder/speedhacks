create table if not exists households (
  id text primary key,
  join_code text not null unique,
  expected_size int not null check (expected_size between 1 and 6),
  confirmed boolean not null default false,
  search_requested_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists housemates (
  id text primary key,
  household_id text not null references households(id) on delete cascade,
  name text not null,
  max_budget_usd int not null,
  commute_destination text not null,
  commute_mode text not null,
  max_commute_minutes int not null,
  must_haves text[] not null default '{}',
  deal_breakers text[] not null default '{}',
  nice_to_haves text[] not null default '{}',
  move_in_from date not null,
  move_in_to date not null,
  income_min int not null,
  income_max int not null,
  google_refresh_token text,
  google_access_token text,
  google_token_expires_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists housemates_household_idx on housemates(household_id);

-- One run per household: a new search replaces the previous run.
create table if not exists agent_runs (
  household_id text primary key references households(id) on delete cascade,
  run jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists tours (
  household_id text not null references households(id) on delete cascade,
  listing_id text not null,
  start_at timestamptz not null,
  end_at timestamptz not null,
  status text not null check (status in ('proposed', 'accepted')),
  calendar_event_ids jsonb not null default '{}',
  primary key (household_id, listing_id)
);

-- Sign-in with Google: the account a housemate joined with, so they can get back in from another browser.
alter table housemates add column if not exists first_name text;
alter table housemates add column if not exists last_name text;
alter table housemates add column if not exists google_sub text;
alter table housemates add column if not exists email text;
-- Where the housemate wants to live; older rows predate the question.
alter table housemates add column if not exists location text;
create unique index if not exists housemates_household_google_idx on housemates(household_id, google_sub);
-- Someone searching alone is a household of one.
alter table households drop constraint if exists households_expected_size_check;
alter table households add constraint households_expected_size_check check (expected_size between 1 and 6);
-- Several ways to commute; commute_mode keeps the first for older readers.
alter table housemates add column if not exists commute_modes text[];
-- The interview after the form: its transcript, and the free-form wishes it turned up.
alter table housemates add column if not exists interview jsonb not null default '[]';
alter table housemates add column if not exists interview_done boolean not null default false;
alter table housemates add column if not exists wishes text[] not null default '{}';
-- The form no longer asks for income or a last name; older rows keep theirs.
alter table housemates alter column income_min drop not null;
alter table housemates alter column income_max drop not null;
