import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kansas Wind Potential",
  description: "An interactive, data-grounded look at wind energy potential across Kansas.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
