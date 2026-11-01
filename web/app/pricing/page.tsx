import type { Metadata } from "next";
import Pricing from "@/components/Pricing";

export const metadata: Metadata = {
  title: "Pricing · Astra / SSA",
  description: "What the Free and Pro plans of the Astra screening console allow, and what Pro costs."
};

export default function PricingPage() {
  return <Pricing />;
}
