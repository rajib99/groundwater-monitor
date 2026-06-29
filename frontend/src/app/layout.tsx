import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Groundwater Monitor",
  description: "Real-time groundwater level monitoring and forecasting",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
