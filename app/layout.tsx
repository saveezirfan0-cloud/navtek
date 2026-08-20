import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "Navtek eOrder",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

// Applies the saved appearance choice and sidebar width before first paint —
// without this, a dark-mode user sees a white flash on every navigation and a
// collapsed sidebar springs open then snaps shut. Kept tiny and inline; the
// matching writers live in app/theme.tsx (THEME_KEY) and app/Sidebar.tsx
// (SIDENAV_KEY).
const THEME_INIT =
  `try{var t=localStorage.getItem("navtek-theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}` +
  `try{if(localStorage.getItem("navtek-sidenav")==="collapsed")document.documentElement.setAttribute("data-sidenav","collapsed")}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-AU" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
