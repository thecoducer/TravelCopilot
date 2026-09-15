"use client";

import { useParams } from "next/navigation";
import { TravelChat } from "@/components/chat/travel-chat";

export default function SessionPage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = Array.isArray(params.sessionId) ? params.sessionId[0] : params.sessionId;
  return <TravelChat key={sessionId} initialSessionId={sessionId} />;
}
