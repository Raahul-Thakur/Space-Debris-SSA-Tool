import AccountPanel from "@/components/AccountPanel";

export const metadata = {
  title: "Account / ASTRA SSA",
  description: "Your plan, your usage this month, and the runs you have made."
};

/**
 * Everything on this page is the signed-in principal's own.
 *
 * The figures come from `/billing/me` and `/screening-jobs`, both of which
 * the API already scopes to the caller, so this page cannot show one account
 * another's usage even if it tried.
 */
export default function AccountPage() {
  return <AccountPanel />;
}
