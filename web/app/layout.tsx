import type { Metadata } from "next";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "driver.js/dist/driver.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Astra / SSA Command",
  description: "Governed space situational awareness command center"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
