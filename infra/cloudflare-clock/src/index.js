/**
 * Alarm clock only. Does not call Finviz.
 * Dispatches GitHub Actions at 09:15 ET (premarket), 09:30 ET (RTH),
 * and 16:30 ET (overnight) on weekdays.
 */
export default {
  async scheduled(event, env) {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      })
        .formatToParts(new Date(event.scheduledTime))
        .map((p) => [p.type, p.value]),
    );
    if (parts.weekday === "Sat" || parts.weekday === "Sun") {
      return;
    }
    const hour = String(parts.hour).padStart(2, "0");
    const minute = String(parts.minute).padStart(2, "0");
    const hm = `${hour}:${minute}`;
    let workflow = null;
    if (hm === "09:15") workflow = "premarket.yml";
    if (hm === "09:30") workflow = "rth.yml";
    if (hm === "16:30") workflow = "overnight.yml";
    if (!workflow) {
      return;
    }
    const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${workflow}/dispatches`;
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "options-desk-clock",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`dispatch ${workflow} failed: ${res.status} ${body}`);
    }
  },
};
