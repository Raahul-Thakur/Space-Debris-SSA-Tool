/**
 * Where the site may send a browser for payment: Dodo Payments' own pages.
 *
 * The checkout and billing-portal links come from our API, which gets them
 * from Dodo. Following any URL the API returns would turn a compromised or
 * misconfigured API into a redirect to a look-alike payment page, so the
 * link is checked here before the browser leaves the site.
 */
const PAYMENT_DOMAIN = "dodopayments.com";

export function isPaymentUrl(candidate: string): boolean {
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return false;
  }
  if (url.protocol !== "https:" || url.username || url.password) return false;
  const host = url.hostname.toLowerCase();
  return host === PAYMENT_DOMAIN || host.endsWith(`.${PAYMENT_DOMAIN}`);
}

/** Send the browser to a payment page, or throw if it is not Dodo's. */
export function goToPayment(candidate: string): void {
  if (!isPaymentUrl(candidate)) {
    throw new Error("The payment link was not a Dodo Payments page, so it was not opened.");
  }
  window.location.assign(candidate);
}
