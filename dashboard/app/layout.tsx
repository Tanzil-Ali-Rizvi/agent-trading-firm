import type { Metadata } from "next";
import "@fontsource/big-shoulders-display/700";
import "@fontsource/big-shoulders-display/800";
import "@fontsource/big-shoulders-display/900";
import "@fontsource/archivo/400.css";
import "@fontsource/archivo/500.css";
import "@fontsource/archivo/600.css";
import "@fontsource/archivo/700.css";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://agent-trading-firm.vercel.app"),
  title: "Agent Trading Firm",
  description:
    "Six AI agent floors (scanner, research, strategy, testing, risk, control) paper-trading 20 liquid crypto coins, with every decision logged and an honest backtest.",
  openGraph: {
    title: "Agent Trading Firm: six AI agent floors, one paper-trading book",
    description: "Every trade has to climb six floors. Live paper trading on Coinbase data, an honest backtest and a public decision log.",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
    type: "website",
  },
  twitter: { card: "summary_large_image", images: ["/og.png"] },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
