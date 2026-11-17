import { createApp, h, nextTick, type App } from "vue";
import { afterEach, expect, it } from "vitest";
import HelpHint from "./HelpHint.vue";
let app: App;
afterEach(() => {
  app?.unmount();
  document.body.innerHTML = "";
});
async function mount() {
  const host = document.createElement("div");
  document.body.append(host);
  app = createApp({
    render: () =>
      h(
        HelpHint,
        { label: "显示名称说明" },
        { default: () => "仅更改显示名称，不更改登录用户名。" },
      ),
  });
  app.mount(host);
  await nextTick();
  return host.querySelector("button")!;
}
it('uses a circled information glyph, not a warning exclamation',async()=>{const button=await mount();expect(button.querySelector('svg circle')).not.toBeNull();expect(button.querySelector('svg path')?.getAttribute('d')).toBe('M12 11v6m0-10h.01');});
it("opens help on keyboard focus in a body portal, describes its trigger and dismisses with Escape", async () => {
  const button = await mount();
  button.focus();
  await nextTick();
  expect(button.getAttribute("aria-expanded")).toBe("true");
  const help = document.getElementById(
    button.getAttribute("aria-describedby")!,
  )!;
  expect(help?.textContent).toContain("不更改登录用户名");
  expect(help.parentElement).toBe(document.body);
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
  );
  await nextTick();
  expect(button.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(button);
});
it("opens on hover and touch-style click; outside pointer dismisses without trapping focus", async () => {
  const button = await mount();
  button.dispatchEvent(new Event("pointerenter"));
  await nextTick();
  expect(button.getAttribute("aria-expanded")).toBe("true");
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  await nextTick();
  button.click();
  await nextTick();
  expect(button.getAttribute("aria-expanded")).toBe("true");
  document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
  await nextTick();
  expect(button.getAttribute("aria-expanded")).toBe("false");
  button.click();
  await nextTick();
  button.click();
  await nextTick();
  expect(button.getAttribute("aria-expanded")).toBe("false");
});
it("returns focus from the scrollable portal on Escape without immediately reopening", async () => {
  const button = await mount();
  button.focus();
  await nextTick();
  const help = document.getElementById(
    button.getAttribute("aria-describedby")!,
  )!;
  help.focus();
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  await nextTick();
  expect(document.activeElement).toBe(button);
  expect(button.getAttribute("aria-expanded")).toBe("false");
});
