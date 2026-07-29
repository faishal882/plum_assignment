import { ReactNode } from "react";
import { TopNav } from "./TopNav";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-canvas text-ink flex flex-col antialiased selection:bg-violet-pale selection:text-violet">
      <TopNav />

      {/* Main 1280px Framed Shell */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-8 py-6">
        <div className="w-full min-h-[calc(100vh-140px)] rounded-frame bg-canvas border border-hairline neu-raised p-4 sm:p-8 space-y-8">
          {children}
        </div>
      </main>

      {/* Operational Footer */}
      <footer className="w-full py-6 mt-8 bg-darkContrast text-white/70 text-xs">
        <div className="max-w-7xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-violet" />
            <span className="font-semibold text-white">Plum Claims Console</span>
            <span className="text-white/40">|</span>
            <span>Explainable Adjudication Platform</span>
          </div>
          <p className="text-white/50 text-center sm:text-right">
            Tactile Operations Interface • Next.js App Router BFF
          </p>
        </div>
      </footer>
    </div>
  );
}
