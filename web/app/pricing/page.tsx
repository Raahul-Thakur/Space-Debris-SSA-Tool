import type { Metadata } from "next";
import Pricing from "@/components/Pricing";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Astra is free during its public beta. See what the Pro plan will add, and join the waitlist to hear when it opens."
};

export default function PricingPage() {
  return <Pricing />;
}
