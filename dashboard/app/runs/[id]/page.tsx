import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { RunDetailView } from "@/components/RunDetailView";
import { ApiError, getRun } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Run detail",
};

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const run = await getRun(id);
    return <RunDetailView run={run} />;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}
