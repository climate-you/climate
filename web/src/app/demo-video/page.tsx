import type { Metadata } from "next";
import { notFound } from "next/navigation";
import DemoVideoClient from "./DemoVideoClient";

export const metadata: Metadata = {
  title: "Demo Video | Your Climate",
  robots: {
    index: false,
    follow: false,
  },
};

export default function DemoVideoPage() {
  if (process.env.NEXT_PUBLIC_ENABLE_DEMO_VIDEO !== "1") {
    notFound();
  }
  return <DemoVideoClient />;
}

