import { Empty } from "../components/ui";

/** Campaigns and chains: list (status, phase x/y, spend vs budget, last activity), detail view and
 *  the New-campaign dialog. Stub: WP5 (campaigns) builds the page on GET /api/campaigns
 *  (lib/api.ts Campaign). */
export function CampaignsPage() {
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1000px] mx-auto px-6 py-5">
        <h1 className="text-lg font-semibold mb-1">Campaigns</h1>
        <p className="text-[13px] text-muted mb-4">Multi-session work with a plan, phases and checks, and one-session workflows.</p>
        <Empty>No campaigns yet.</Empty>
      </div>
    </div>
  );
}
