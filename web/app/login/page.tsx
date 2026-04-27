"use client";
/**
 * Login page.
 * Redirects to /authorize on the Python server to start Google OAuth.
 * After OAuth the callback page postMessages the JWT token back.
 * We listen for that message here and store it, then navigate to /profile.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BASE_URL, setToken, getToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [status, setStatus] = useState<"idle" | "waiting" | "done">("idle");

  // If already logged in, skip straight to profile
  useEffect(() => {
    if (getToken()) router.replace("/profile");
  }, [router]);

  // Listen for the OAuth postMessage from the callback popup
  useEffect(() => {
    function onMessage(e: MessageEvent) {
      const data = e.data;
      if (data?.access_token) {
        setToken(data.access_token);
        setStatus("done");
        router.replace("/profile");
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [router]);

  function handleLogin() {
    setStatus("waiting");
    // Open the Python server's /authorize endpoint in a popup
    const w = 500, h = 600;
    const left = window.screenX + (window.outerWidth - w) / 2;
    const top = window.screenY + (window.outerHeight - h) / 2;
    window.open(
      `${BASE_URL}/authorize`,
      "hc-login",
      `width=${w},height=${h},left=${left},top=${top}`
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 flex flex-col items-center gap-6 w-full max-w-sm">
        <div className="flex flex-col items-center gap-2">
          <span className="text-3xl">🏥</span>
          <h1 className="text-xl font-semibold text-gray-900">Health Connector</h1>
          <p className="text-sm text-gray-500 text-center">Personal health data dashboard</p>
        </div>

        {status === "waiting" ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-gray-500">Waiting for Google login…</p>
          </div>
        ) : (
          <button
            onClick={handleLogin}
            className="w-full flex items-center justify-center gap-3 px-4 py-2.5 bg-white border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors shadow-sm"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
            Continue with Google
          </button>
        )}
      </div>
    </div>
  );
}
