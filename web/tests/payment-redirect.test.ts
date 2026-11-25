import { describe, expect, it } from "vitest";
import { isPaymentUrl } from "@/lib/paymentRedirect";

describe("isPaymentUrl", () => {
  it("accepts Dodo's checkout and portal pages", () => {
    expect(isPaymentUrl("https://checkout.dodopayments.com/buy/abc")).toBe(true);
    expect(isPaymentUrl("https://test.checkout.dodopayments.com/session/1")).toBe(true);
    expect(isPaymentUrl("https://dodopayments.com/portal")).toBe(true);
  });

  it("refuses anything else", () => {
    for (const url of [
      "https://evil.example/checkout.dodopayments.com",
      "https://dodopayments.com.evil.example/",
      "https://notdodopayments.com/",
      "http://checkout.dodopayments.com/",
      "javascript:alert(1)",
      "https://user:pw@checkout.dodopayments.com/",
      "/relative",
      ""
    ]) {
      expect(isPaymentUrl(url), url).toBe(false);
    }
  });
});
