import type { Metadata } from "next";
import { THEME_BOOTSTRAP } from "@/lib/theme";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "driver.js/dist/driver.css";
import "./globals.css";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://astra-ssa.vercel.app";
const DESCRIPTION =
  "See which satellites and space debris are about to pass too close. Astra screens " +
  "public orbital data for close approaches and shows them on a live 3D globe. Free public beta.";

/*
 * What a shared link shows on Instagram, LinkedIn, Reddit and messaging apps.
 * The preview image, favicon and app icon are the files beside this one
 * (opengraph-image.png, twitter-image.png, icon.png, apple-icon.png,
 * favicon.ico), which Next turns into the matching tags. `metadataBase`
 * makes those image URLs absolute, which crawlers require.
 */
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Astra / SSA · Space debris close-approach screening",
    template: "%s · Astra / SSA"
  },
  description: DESCRIPTION,
  applicationName: "Astra / SSA",
  openGraph: {
    type: "website",
    siteName: "Astra / SSA",
    title: "Astra / SSA · See which satellites are about to pass too close",
    description: DESCRIPTION,
    url: "/"
  },
  twitter: {
    card: "summary_large_image",
    title: "Astra / SSA · See which satellites are about to pass too close",
    description: DESCRIPTION
  }
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
