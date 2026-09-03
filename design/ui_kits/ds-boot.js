// Kit bootstrap: exposes the design-system namespace as globals for the screen files, and
// backfills any component the on-disk bundle is missing by compiling it from source
// (the bundle is regenerated between turns, so a freshly edited component can lag).
// Sets window.__dsReady — mount scripts await it before rendering.
(() => {
  const NS_KEY = "WarmlineDesignSystem_273f7f";
  const BASE = "../../";
  const SOURCES = {
    Icon: "components/core/Icon.jsx", Card: "components/core/Card.jsx", Badge: "components/core/Badge.jsx",
    Tag: "components/core/Tag.jsx", Button: "components/core/Button.jsx", IconButton: "components/core/IconButton.jsx",
    Input: "components/forms/Input.jsx", Select: "components/forms/Select.jsx", Checkbox: "components/forms/Checkbox.jsx",
    Radio: "components/forms/Radio.jsx", Switch: "components/forms/Switch.jsx", Tabs: "components/navigation/Tabs.jsx",
    Dialog: "components/feedback/Dialog.jsx", Toast: "components/feedback/Toast.jsx", Tooltip: "components/feedback/Tooltip.jsx",
  };
  window.__dsReady = (async () => {
    const ns = window[NS_KEY] || (window[NS_KEY] = {});
    const missing = Object.keys(SOURCES).filter((n) => typeof ns[n] !== "function");
    if (missing.length) {
      const mods = {};
      const req = (spec) => (spec === "react" ? window.React : mods[spec.split("/").pop().replace(/\.jsx?$/, "")] || {});
      for (const name of Object.keys(SOURCES)) {
        const src = await (await fetch(BASE + SOURCES[name])).text();
        const code = Babel.transform(src, { presets: ["react"], plugins: [["transform-modules-commonjs", { strictMode: false }]] }).code;
        const mod = { exports: {} };
        new Function("module", "exports", "require", code)(mod, mod.exports, req);
        mods[name] = mod.exports;
        ns[name] = mod.exports[name];
      }
      console.info("[ds-boot] compiled " + Object.keys(SOURCES).length + " components from source (bundle missing: " + missing.join(", ") + ")");
    }
    Object.assign(window, ns);
  })();
})();
