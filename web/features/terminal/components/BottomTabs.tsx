"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PositionsTable } from "./PositionsTable";
import { OrdersTable } from "./OrdersTable";
import { TradeHistoryTable } from "./TradeHistoryTable";
import { ExecutionsTable } from "./ExecutionsTable";
import { SystemEvents } from "./SystemEvents";

export function BottomTabs() {
  return (
    <Tabs defaultValue="positions" className="flex h-full min-h-0 flex-col gap-0">
      <TabsList className="h-8 w-fit rounded-none border-b bg-transparent p-0">
        <TabsTrigger value="positions" className="cursor-pointer rounded-none data-[state=active]:shadow-none">
          Positions
        </TabsTrigger>
        <TabsTrigger value="orders" className="cursor-pointer rounded-none data-[state=active]:shadow-none">
          Orders
        </TabsTrigger>
        <TabsTrigger value="history" className="cursor-pointer rounded-none data-[state=active]:shadow-none">
          Trade History
        </TabsTrigger>
        <TabsTrigger value="executions" className="cursor-pointer rounded-none data-[state=active]:shadow-none">
          Executions
        </TabsTrigger>
        <TabsTrigger value="events" className="cursor-pointer rounded-none data-[state=active]:shadow-none">
          System Events
        </TabsTrigger>
      </TabsList>
      <TabsContent value="positions" className="min-h-0 flex-1 overflow-y-auto">
        <PositionsTable />
      </TabsContent>
      <TabsContent value="orders" className="min-h-0 flex-1 overflow-y-auto">
        <OrdersTable />
      </TabsContent>
      <TabsContent value="history" className="min-h-0 flex-1 overflow-y-auto">
        <TradeHistoryTable />
      </TabsContent>
      <TabsContent value="executions" className="min-h-0 flex-1 overflow-y-auto">
        <ExecutionsTable />
      </TabsContent>
      <TabsContent value="events" className="min-h-0 flex-1 overflow-hidden">
        <SystemEvents />
      </TabsContent>
    </Tabs>
  );
}
