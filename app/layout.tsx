import type { Metadata } from "next";
import { Figtree, IBM_Plex_Mono, Newsreader } from "next/font/google";
import "./globals.css";

const text = Figtree({ variable: "--font-text-face", subsets: ["latin"] });
const display = Newsreader({
  variable: "--font-display-face",
  subsets: ["latin"],
  style: ["normal", "italic"],
  axes: ["opsz"],
});
const data = IBM_Plex_Mono({ variable: "--font-data-face", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "Keyhunt",
  description: "Find a place in the US for your whole group, checked by phone before you see it.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${text.variable} ${display.variable} ${data.variable}`}>
      <body className="min-h-dvh">{children}</body>
    </html>
  );
}
