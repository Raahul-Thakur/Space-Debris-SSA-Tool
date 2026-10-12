import type { Metadata } from "next";
import { THEME_BOOTSTRAP } from "@/lib/theme";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "driver.js/dist/driver.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Astra / SSA Command",
  description: "Governed space situational awareness command center"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          Runs before the first paint so a visitor who chose dark never sees a
          white flash. It sets an attribute the server did not render, which
          is exactly the mismatch `suppressHydrationWarning` exists for.
        */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
