"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity, BarChart3, CandlestickChart, History, LayoutDashboard, Rss, Wallet,
} from "lucide-react";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent,
  SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuBadge,
  SidebarMenuButton, SidebarMenuItem,
} from "@/components/ui/sidebar";
import { StatusBadge } from "@/components/status-badge";
import { ConnectionIndicator } from "@/components/connection-indicator";

type NavItem = {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  live: boolean; // false renders a "Soon" badge and no navigation yet
};

const NAV_ITEMS: NavItem[] = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard, live: true },
  { title: "Terminal", href: "/terminal", icon: CandlestickChart, live: true },
  { title: "Positions", href: "/positions", icon: Wallet, live: true },
  { title: "Trade History", href: "/trades", icon: History, live: true },
  { title: "Signals", href: "/signals", icon: Rss, live: true },
  { title: "Analytics", href: "/analytics", icon: BarChart3, live: true },
  { title: "Bot Monitoring", href: "/bot", icon: Activity, live: true },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="border-b border-sidebar-border px-3 py-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <CandlestickChart className="size-5 shrink-0 text-bull" />
          <span className="truncate text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
            Signal Terminal
          </span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Trading</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map((item) => {
                const active = item.live && pathname.startsWith(item.href);
                return (
                  <SidebarMenuItem key={item.href}>
                    {item.live ? (
                      <SidebarMenuButton asChild isActive={active} tooltip={item.title}>
                        <Link href={item.href}>
                          <item.icon className="size-4" />
                          <span>{item.title}</span>
                        </Link>
                      </SidebarMenuButton>
                    ) : (
                      <SidebarMenuButton disabled tooltip={`${item.title} — coming soon`}>
                        <item.icon className="size-4" />
                        <span>{item.title}</span>
                      </SidebarMenuButton>
                    )}
                    {!item.live && <SidebarMenuBadge>Soon</SidebarMenuBadge>}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="gap-2 border-t border-sidebar-border px-3 py-3 group-data-[collapsible=icon]:hidden">
        <StatusBadge />
        <ConnectionIndicator />
      </SidebarFooter>
    </Sidebar>
  );
}
