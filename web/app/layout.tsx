import type { Metadata } from "next";
import { Fira_Code, Fira_Sans } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { WsProvider } from "@/components/ws-provider";
import { AppSidebar } from "@/components/app-sidebar";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";

const firaSans = Fira_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

const firaCode = Fira_Code({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Signal Terminal",
  description: "Real-time paper-trading dashboard for the Telegram signal bot",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${firaSans.variable} ${firaCode.variable} dark h-full antialiased`}>
      <body className="h-full">
        <Providers>
          <WsProvider>
            <SidebarProvider>
              <AppSidebar />
              <SidebarInset>
                <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
                  <SidebarTrigger />
                  <Separator orientation="vertical" className="mr-1 h-4" />
                  <span className="text-sm font-medium text-muted-foreground">
                    Paper trading — simulated executions only
                  </span>
                </header>
                <main className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</main>
              </SidebarInset>
            </SidebarProvider>
          </WsProvider>
        </Providers>
      </body>
    </html>
  );
}
