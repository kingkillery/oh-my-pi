// @ts-nocheck — example file; install @pk-nerdsaver-ai/pi-coding-agent before running
import type { ExtensionAPI } from "@pk-nerdsaver-ai/pi-coding-agent";

export default function myPlugin(pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    ctx.ui.notify("my-plugin loaded from example marketplace!", "info");
  });
}
