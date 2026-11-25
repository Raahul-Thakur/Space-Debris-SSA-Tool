import AdminStats from "@/components/AdminStats";

export const metadata = {
  title: "Usage",
  robots: { index: false, follow: false },
  description: "Aggregate usage figures for administrators."
};

/**
 * Aggregate usage for an administrator: active accounts, sign-ups,
 * screenings and live API latency, all from `/admin/stats`.
 *
 * The static page is the same for everyone and holds no figures; they are
 * fetched with the visitor's token, and the API refuses anyone below admin.
 * Left out of the sitemap and marked noindex: there is nothing here for a
 * search engine.
 */
export default function AdminPage() {
  return <AdminStats />;
}
