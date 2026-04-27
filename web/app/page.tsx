"use client";
// Root: redirect to /profile if logged in, else to /login
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

export default function Root() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/profile" : "/login");
  }, [router]);
  return null;
}
