import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Groundwater Monitor",
  description: "Real-time groundwater level monitoring and forecasting",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0a0e1a] text-slate-100 antialiased">
        {children}
      </body>
    </html>
  );
}
