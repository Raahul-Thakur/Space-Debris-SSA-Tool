import { afterEach, describe, expect, it } from "vitest";
import { consumeReturnTo, rememberReturnTo } from "@/lib/returnTo";

describe("return after sign-in", () => {
  afterEach(() => window.sessionStorage.clear());

  it("returns a remembered page once", () => {
    rememberReturnTo("/pricing");
    expect(consumeReturnTo()).toBe("/pricing");
    expect(consumeReturnTo()).toBeNull();
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "pricing"])(
    "refuses %s, which would leave the site",
    (path) => {
      rememberReturnTo(path);
      expect(consumeReturnTo()).toBeNull();
    }
  );

  it("ignores a tampered stored value", () => {
    window.sessionStorage.setItem("astra.return-to", "//evil.example");
    expect(consumeReturnTo()).toBeNull();
  });
});
