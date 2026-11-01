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
  title: "Agent Trading Firm",
  description:
    "Six AI agent floors (scanner, research, strategy, testing, risk, control) paper-trading 20 liquid crypto coins, with every decision logged and an honest backtest.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
