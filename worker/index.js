// Cloudflare Worker for news.slanesens.com.
//
// fetch:     serves the static site from site/ (same as before; assets binding).
// scheduled: starts the daily GitHub Actions run at 05:00 Swedish time. GitHub's own `schedule`
//            trigger is best-effort and started runs 5–8 hours late (Nov 2026), while Cloudflare
//            cron triggers fire on time. Both UTC candidates fire (03:00 and 04:00, see
//            wrangler.jsonc) and only the one that is 05:00 in Stockholm dispatches, so this
//            follows daylight saving time like the gate job in daily.yml.
//
// Needs the secret GITHUB_TOKEN: a fine-grained token for this repo only, permission
// "Actions: Read and write". Set it in the Cloudflare dashboard (Worker → Settings →
// Variables and Secrets) or with `npx wrangler secret put GITHUB_TOKEN`.

const REPO = "GustavSS-Git/AI_newsletter";
const WORKFLOW = "daily.yml";

export function stockholmHour(date) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Stockholm", hour: "2-digit", hourCycle: "h23",
  }).format(date);
}

export default {
  async fetch(request, env) {
    return env.ASSETS.fetch(request);
  },

  async scheduled(controller, env) {
    const hour = stockholmHour(new Date(controller.scheduledTime));
    if (hour !== "05") {
      console.log(`cron ${controller.cron}: ${hour}:00 in Stockholm, not 05:00; skipping`);
      return;
    }
    if (!env.GITHUB_TOKEN) throw new Error("GITHUB_TOKEN secret is not set");
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-daily-cron",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    if (!r.ok) {
      // Throwing marks the cron invocation as failed in the Cloudflare dashboard.
      throw new Error(`workflow dispatch failed: HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
    }
    console.log(`cron ${controller.cron}: dispatched ${WORKFLOW} on main`);
  },
};
