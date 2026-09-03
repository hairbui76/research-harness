/* @ds-bundle: {"format":4,"namespace":"WarmlineDesignSystem_273f7f","components":[{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Card","sourcePath":"components/core/Card.jsx"},{"name":"Icon","sourcePath":"components/core/Icon.jsx"},{"name":"IconButton","sourcePath":"components/core/IconButton.jsx"},{"name":"Tag","sourcePath":"components/core/Tag.jsx"},{"name":"Dialog","sourcePath":"components/feedback/Dialog.jsx"},{"name":"Toast","sourcePath":"components/feedback/Toast.jsx"},{"name":"Tooltip","sourcePath":"components/feedback/Tooltip.jsx"},{"name":"Checkbox","sourcePath":"components/forms/Checkbox.jsx"},{"name":"Input","sourcePath":"components/forms/Input.jsx"},{"name":"Radio","sourcePath":"components/forms/Radio.jsx"},{"name":"Select","sourcePath":"components/forms/Select.jsx"},{"name":"Switch","sourcePath":"components/forms/Switch.jsx"},{"name":"Tabs","sourcePath":"components/navigation/Tabs.jsx"}],"sourceHashes":{"components/core/Badge.jsx":"ebcce454306c","components/core/Button.jsx":"28ef6352b91d","components/core/Card.jsx":"cf50a15082ba","components/core/Icon.jsx":"7a63fb3b3445","components/core/IconButton.jsx":"5cfc0d92e442","components/core/Tag.jsx":"bd376a550dae","components/feedback/Dialog.jsx":"1d4e66d6752a","components/feedback/Toast.jsx":"fafb495cbc45","components/feedback/Tooltip.jsx":"423e3e4be02e","components/forms/Checkbox.jsx":"1144adde884f","components/forms/Input.jsx":"8326d6dfc432","components/forms/Radio.jsx":"955dd0e65f52","components/forms/Select.jsx":"c7f13856936a","components/forms/Switch.jsx":"b1b1ffb05b30","components/navigation/Tabs.jsx":"1cc0833489e6","ui_kits/app/AppChrome.jsx":"18b3244a6fd2","ui_kits/app/InboxScreen.jsx":"72b4ff248b31","ui_kits/app/LoginScreen.jsx":"0bd17fe3eb5f","ui_kits/app/ReportsScreen.jsx":"21bb8d28bca3","ui_kits/app/SettingsScreen.jsx":"da47d962bae9","ui_kits/ds-boot.js":"1055d0116c48","ui_kits/marketing/ArticleScreen.jsx":"5ed3d32e188c","ui_kits/marketing/Chrome.jsx":"19c989c54af3","ui_kits/marketing/HomeScreen.jsx":"574a8d80b1b8","ui_kits/marketing/PricingScreen.jsx":"fd55c57b0879","ui_kits/marketing/ProductScreen.jsx":"2d02801b4fd5"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.WarmlineDesignSystem_273f7f = window.WarmlineDesignSystem_273f7f || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const TONES = {
  neutral: {
    bg: "var(--ink-10)",
    fg: "var(--text-primary)"
  },
  accent: {
    bg: "var(--color-fin)",
    fg: "var(--color-white)"
  },
  success: {
    bg: "var(--color-report-green)",
    fg: "var(--color-off-black)"
  },
  error: {
    bg: "var(--color-report-red)",
    fg: "var(--color-white)"
  },
  info: {
    bg: "var(--color-report-blue)",
    fg: "var(--color-off-black)"
  },
  inverse: {
    bg: "var(--surface-inverse)",
    fg: "var(--text-inverse)"
  }
};
function Badge({
  children,
  tone = "neutral",
  style,
  ...rest
}) {
  const t = TONES[tone] || TONES.neutral;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      height: 20,
      padding: "0 6px",
      background: t.bg,
      color: t.fg,
      fontFamily: "var(--font-mono)",
      fontSize: "var(--type-mono-size)",
      lineHeight: 1,
      letterSpacing: "var(--type-mono-ls)",
      textTransform: "uppercase",
      borderRadius: "var(--radius-button)",
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const SIZES = {
  md: {
    height: 40,
    padding: "0 14px",
    fontSize: "var(--type-button-size)",
    lineHeight: "var(--type-button-lh)",
    gap: 8
  },
  sm: {
    height: 32,
    padding: "0 12px",
    fontSize: "var(--type-button-sm-size)",
    lineHeight: "var(--type-button-sm-lh)",
    gap: 6
  },
  lg: {
    height: 48,
    padding: "0 20px",
    fontSize: "var(--type-button-size)",
    lineHeight: "var(--type-button-lh)",
    gap: 10
  }
};
function palette(variant) {
  switch (variant) {
    case "outlined":
      return {
        bg: "transparent",
        fg: "var(--text-primary)",
        border: "1px solid var(--border-strong)",
        hoverBg: "var(--surface-inverse)",
        hoverFg: "var(--text-inverse)"
      };
    case "warm":
      return {
        bg: "var(--surface-card)",
        fg: "var(--text-primary)",
        border: "1px solid var(--border-subtle)",
        hoverBg: "var(--color-white)",
        hoverFg: "var(--text-primary)"
      };
    case "accent":
      return {
        bg: "var(--button-accent-bg)",
        fg: "var(--button-accent-fg)",
        border: "1px solid transparent",
        hoverBg: "var(--color-white)",
        hoverFg: "var(--color-fin)"
      };
    case "ghost":
      return {
        bg: "transparent",
        fg: "var(--text-primary)",
        border: "1px solid transparent",
        hoverBg: "var(--ink-10)",
        hoverFg: "var(--text-primary)"
      };
    default:
      return {
        bg: "var(--button-primary-bg)",
        fg: "var(--button-primary-fg)",
        border: "1px solid var(--border-strong)",
        hoverBg: "var(--button-primary-bg-hover)",
        hoverFg: "var(--button-primary-fg-hover)"
      };
  }
}
function Button({
  variant = "primary",
  size = "md",
  children,
  disabled = false,
  fullWidth = false,
  href,
  onClick,
  type = "button",
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);
  const s = SIZES[size] || SIZES.md;
  const p = palette(variant);
  const on = hover && !disabled;
  const css = {
    display: fullWidth ? "flex" : "inline-flex",
    width: fullWidth ? "100%" : undefined,
    alignItems: "center",
    justifyContent: "center",
    gap: s.gap,
    height: s.height,
    padding: s.padding,
    fontFamily: "var(--font-sans)",
    fontSize: s.fontSize,
    lineHeight: s.lineHeight,
    fontWeight: 400,
    borderRadius: "var(--radius-button)",
    border: p.border,
    background: active && !disabled ? "var(--button-primary-bg-active)" : on ? p.hoverBg : p.bg,
    color: active && !disabled ? "var(--text-inverse)" : on ? p.hoverFg : p.fg,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.4 : 1,
    transform: active && !disabled ? "scale(var(--active-scale))" : on ? "scale(var(--hover-scale))" : "scale(1)",
    transition: "var(--transition-button)",
    textDecoration: "none",
    whiteSpace: "nowrap",
    ...style
  };
  const handlers = {
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => {
      setHover(false);
      setActive(false);
    },
    onMouseDown: () => setActive(true),
    onMouseUp: () => setActive(false)
  };
  if (href && !disabled) return /*#__PURE__*/React.createElement("a", _extends({
    href: href,
    style: css
  }, handlers, rest), children);
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    onClick: onClick,
    style: css
  }, handlers, rest), children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Card({
  children,
  padding = 24,
  tone = "cream",
  interactive = false,
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  const bg = tone === "white" ? "var(--surface-primary)" : tone === "inverse" ? "var(--surface-inverse)" : "var(--surface-card)";
  return /*#__PURE__*/React.createElement("div", _extends({
    onMouseEnter: interactive ? () => setHover(true) : undefined,
    onMouseLeave: interactive ? () => setHover(false) : undefined,
    style: {
      background: bg,
      color: tone === "inverse" ? "var(--text-inverse)" : "var(--text-primary)",
      border: `1px solid ${tone === "inverse" ? "var(--color-off-black)" : "var(--border-default)"}`,
      borderRadius: "var(--radius-card)",
      padding,
      boxShadow: "var(--shadow-card)",
      transition: "border-color var(--duration-base) linear, background-color var(--duration-base) linear",
      borderColor: hover ? "var(--border-strong)" : undefined,
      cursor: interactive ? "pointer" : undefined,
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Card.jsx", error: String((e && e.message) || e) }); }

// components/core/Icon.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
// Lucide (CDN) is the substituted icon set — see readme.md ICONOGRAPHY.
const CDN = "https://unpkg.com/lucide-static@0.544.0/icons/";
function Icon({
  name,
  size = 20,
  strokeWidth,
  color = "currentColor",
  style,
  ...rest
}) {
  const url = `url("${CDN}${name}.svg")`;
  return /*#__PURE__*/React.createElement("span", _extends({
    role: "img",
    "aria-label": name,
    style: {
      display: "inline-block",
      width: size,
      height: size,
      flex: "0 0 auto",
      backgroundColor: color,
      WebkitMaskImage: url,
      maskImage: url,
      WebkitMaskRepeat: "no-repeat",
      maskRepeat: "no-repeat",
      WebkitMaskSize: "contain",
      maskSize: "contain",
      ...style
    }
  }, rest));
}
Object.assign(__ds_scope, { Icon });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Icon.jsx", error: String((e && e.message) || e) }); }

// components/core/IconButton.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const SIZES = {
  sm: 28,
  md: 34,
  lg: 40
};
function IconButton({
  name,
  size = "md",
  variant = "ghost",
  label,
  disabled = false,
  onClick,
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);
  const box = SIZES[size] || SIZES.md;
  const solid = variant === "solid";
  const outlined = variant === "outlined";
  const on = hover && !disabled;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    "aria-label": label || name,
    disabled: disabled,
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => {
      setHover(false);
      setActive(false);
    },
    onMouseDown: () => setActive(true),
    onMouseUp: () => setActive(false),
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: box,
      height: box,
      padding: 0,
      borderRadius: "var(--radius-nav)",
      border: outlined ? "1px solid var(--border-default)" : "1px solid transparent",
      background: solid ? on ? "var(--color-white)" : "var(--surface-inverse)" : on ? "var(--ink-10)" : "transparent",
      color: solid ? on ? "var(--text-primary)" : "var(--text-inverse)" : "var(--text-secondary)",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1,
      transform: active && !disabled ? "scale(var(--active-scale))" : "scale(1)",
      transition: "var(--transition-button)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: name,
    size: Math.round(box * 0.5)
  }));
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/core/Tag.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Tag({
  children,
  onRemove,
  selected = false,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      height: 28,
      padding: "0 10px",
      whiteSpace: "nowrap",
      background: selected ? "var(--surface-inverse)" : "var(--surface-card)",
      color: selected ? "var(--text-inverse)" : "var(--text-primary)",
      border: `1px solid ${selected ? "var(--color-off-black)" : "var(--border-default)"}`,
      borderRadius: "var(--radius-button)",
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-sm-size)",
      fontWeight: 400,
      ...style
    }
  }, rest), children, onRemove && /*#__PURE__*/React.createElement("button", {
    onClick: onRemove,
    "aria-label": "Remove",
    style: {
      display: "inline-flex",
      padding: 0,
      border: 0,
      background: "none",
      cursor: "pointer",
      color: "inherit"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 12
  })));
}
Object.assign(__ds_scope, { Tag });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Tag.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Dialog.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Dialog({
  open = false,
  title,
  description,
  children,
  footer,
  onClose,
  width = 440,
  style,
  ...rest
}) {
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "fixed",
      inset: 0,
      zIndex: 60,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--ink-30)",
      backdropFilter: "blur(2px)"
    },
    onClick: onClose
  }, /*#__PURE__*/React.createElement("div", _extends({
    role: "dialog",
    "aria-modal": "true",
    onClick: e => e.stopPropagation(),
    style: {
      width,
      maxWidth: "calc(100vw - 32px)",
      padding: 24,
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      gap: 16,
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h4", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-h4-size)",
      lineHeight: 1,
      letterSpacing: "var(--type-h4-ls)",
      fontWeight: 400
    }
  }, title), description && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "10px 0 0",
      fontSize: "var(--type-body-size)",
      color: "var(--text-muted)"
    }
  }, description)), onClose && /*#__PURE__*/React.createElement(__ds_scope.IconButton, {
    name: "x",
    size: "sm",
    label: "Close",
    onClick: onClose
  })), children && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 20
    }
  }, children), footer && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: 8,
      marginTop: 24
    }
  }, footer)));
}
Object.assign(__ds_scope, { Dialog });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Dialog.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Toast.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const ICONS = {
  neutral: "info",
  success: "check-circle",
  error: "alert-circle",
  info: "info"
};
function Toast({
  title,
  description,
  tone = "neutral",
  onDismiss,
  style,
  ...rest
}) {
  const accent = tone === "success" ? "var(--feedback-success)" : tone === "error" ? "var(--feedback-error)" : tone === "info" ? "var(--feedback-info)" : "var(--color-fin)";
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: "flex",
      alignItems: "flex-start",
      gap: 12,
      width: 340,
      padding: 16,
      background: "var(--surface-inverse)",
      color: "var(--text-inverse)",
      border: "1px solid var(--color-off-black)",
      borderRadius: "var(--radius-card)",
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: ICONS[tone] || "info",
    size: 18,
    color: accent,
    style: {
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-size)",
      letterSpacing: "-0.1px"
    }
  }, title), description && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 4,
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-sm-size)",
      fontWeight: 300,
      color: "var(--color-sand)"
    }
  }, description)), onDismiss && /*#__PURE__*/React.createElement("button", {
    onClick: onDismiss,
    "aria-label": "Dismiss",
    style: {
      display: "inline-flex",
      border: 0,
      background: "none",
      padding: 0,
      cursor: "pointer",
      color: "var(--color-sand)"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 14
  })));
}
Object.assign(__ds_scope, { Toast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Toast.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Tooltip.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Tooltip({
  content,
  children,
  placement = "top",
  style,
  ...rest
}) {
  const [open, setOpen] = React.useState(false);
  const pos = placement === "bottom" ? {
    top: "calc(100% + 6px)",
    left: "50%",
    transform: "translateX(-50%)"
  } : {
    bottom: "calc(100% + 6px)",
    left: "50%",
    transform: "translateX(-50%)"
  };
  return /*#__PURE__*/React.createElement("span", _extends({
    onMouseEnter: () => setOpen(true),
    onMouseLeave: () => setOpen(false),
    style: {
      position: "relative",
      display: "inline-flex",
      ...style
    }
  }, rest), children, open && /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      ...pos,
      zIndex: 40,
      whiteSpace: "nowrap",
      background: "var(--surface-inverse)",
      color: "var(--text-inverse)",
      padding: "6px 8px",
      borderRadius: "var(--radius-button)",
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-sm-size)",
      fontWeight: 300,
      lineHeight: 1.4
    }
  }, content));
}
Object.assign(__ds_scope, { Tooltip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Tooltip.jsx", error: String((e && e.message) || e) }); }

// components/forms/Checkbox.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Checkbox({
  label,
  checked,
  defaultChecked,
  onChange,
  disabled = false,
  style,
  ...rest
}) {
  const [internal, setInternal] = React.useState(!!defaultChecked);
  const isOn = checked === undefined ? internal : checked;
  function toggle(e) {
    if (disabled) return;
    if (checked === undefined) setInternal(!isOn);
    if (onChange) onChange(!isOn, e);
  }
  return /*#__PURE__*/React.createElement("label", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 10,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    onClick: toggle,
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: 18,
      height: 18,
      borderRadius: "var(--radius-button)",
      background: isOn ? "var(--surface-inverse)" : "var(--surface-primary)",
      border: "1px solid " + (isOn ? "var(--color-off-black)" : "var(--border-default)"),
      transition: "background-color var(--duration-fast) linear"
    }
  }, isOn && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "check",
    size: 12,
    color: "var(--text-inverse)"
  })), label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-size)"
    }
  }, label));
}
Object.assign(__ds_scope, { Checkbox });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Checkbox.jsx", error: String((e && e.message) || e) }); }

// components/forms/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Input({
  label,
  hint,
  error,
  iconLeft,
  size = "md",
  style,
  id,
  ...rest
}) {
  const [focus, setFocus] = React.useState(false);
  const inputId = id || (label ? "in-" + String(label).toLowerCase().replace(/[^a-z0-9]+/g, "-") : undefined);
  const height = size === "sm" ? 32 : 40;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8,
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("label", {
    htmlFor: inputId,
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--type-mono-size)",
      letterSpacing: "var(--type-mono-ls)",
      textTransform: "uppercase",
      color: "var(--text-muted)"
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      height,
      padding: "0 12px",
      background: "var(--surface-primary)",
      border: "1px solid " + (error ? "var(--feedback-error)" : focus ? "var(--border-strong)" : "var(--border-default)"),
      borderRadius: "var(--radius-button)",
      transition: "border-color var(--duration-fast) linear"
    }
  }, iconLeft && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconLeft,
    size: 16,
    color: "var(--text-muted)"
  }), /*#__PURE__*/React.createElement("input", _extends({
    id: inputId,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    style: {
      flex: 1,
      minWidth: 0,
      height: "100%",
      border: 0,
      outline: "none",
      background: "transparent",
      fontFamily: "var(--font-sans)",
      fontSize: size === "sm" ? "var(--type-body-sm-size)" : "var(--type-body-size)",
      color: "var(--text-primary)"
    }
  }, rest))), (error || hint) && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-sm-size)",
      fontWeight: 300,
      color: error ? "var(--feedback-error)" : "var(--text-muted)"
    }
  }, error || hint));
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Input.jsx", error: String((e && e.message) || e) }); }

// components/forms/Radio.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Radio({
  label,
  checked,
  name,
  value,
  onChange,
  disabled = false,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("label", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 10,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: 18,
      height: 18,
      borderRadius: "var(--radius-pill)",
      background: "var(--surface-primary)",
      border: "1px solid " + (checked ? "var(--color-off-black)" : "var(--border-default)")
    }
  }, checked && /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: "var(--radius-pill)",
      background: "var(--surface-inverse)"
    }
  })), /*#__PURE__*/React.createElement("input", {
    type: "radio",
    name: name,
    value: value,
    checked: !!checked,
    onChange: onChange,
    disabled: disabled,
    style: {
      position: "absolute",
      opacity: 0,
      width: 0,
      height: 0
    }
  }), label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-size)"
    }
  }, label));
}
Object.assign(__ds_scope, { Radio });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Radio.jsx", error: String((e && e.message) || e) }); }

// components/forms/Select.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Select({
  label,
  options = [],
  value,
  onChange,
  size = "md",
  style,
  id,
  ...rest
}) {
  const [focus, setFocus] = React.useState(false);
  const height = size === "sm" ? 32 : 40;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8,
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("label", {
    htmlFor: id,
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "var(--type-mono-size)",
      letterSpacing: "var(--type-mono-ls)",
      textTransform: "uppercase",
      color: "var(--text-muted)"
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      display: "flex",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("select", _extends({
    id: id,
    value: value,
    onChange: onChange,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    style: {
      appearance: "none",
      width: "100%",
      height,
      padding: "0 34px 0 12px",
      background: "var(--surface-primary)",
      color: "var(--text-primary)",
      border: "1px solid " + (focus ? "var(--border-strong)" : "var(--border-default)"),
      borderRadius: "var(--radius-button)",
      outline: "none",
      fontFamily: "var(--font-sans)",
      fontSize: size === "sm" ? "var(--type-body-sm-size)" : "var(--type-body-size)"
    }
  }, rest), options.map(function (o) {
    const opt = typeof o === "string" ? {
      value: o,
      label: o
    } : o;
    return /*#__PURE__*/React.createElement("option", {
      key: opt.value,
      value: opt.value
    }, opt.label);
  })), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "chevron-down",
    size: 16,
    color: "var(--text-muted)",
    style: {
      position: "absolute",
      right: 12,
      pointerEvents: "none"
    }
  })));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Select.jsx", error: String((e && e.message) || e) }); }

// components/forms/Switch.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Switch({
  label,
  checked,
  defaultChecked,
  onChange,
  disabled = false,
  style,
  ...rest
}) {
  const [internal, setInternal] = React.useState(!!defaultChecked);
  const isOn = checked === undefined ? internal : checked;
  function toggle() {
    if (disabled) return;
    if (checked === undefined) setInternal(!isOn);
    if (onChange) onChange(!isOn);
  }
  return /*#__PURE__*/React.createElement("label", _extends({
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 10,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    role: "switch",
    "aria-checked": isOn,
    onClick: toggle,
    style: {
      position: "relative",
      display: "inline-block",
      width: 36,
      height: 20,
      borderRadius: "var(--radius-button)",
      background: isOn ? "var(--surface-inverse)" : "var(--color-sand)",
      border: "1px solid " + (isOn ? "var(--color-off-black)" : "var(--border-default)"),
      transition: "background-color var(--duration-base) linear"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: 2,
      left: isOn ? 18 : 2,
      width: 14,
      height: 14,
      borderRadius: 2,
      background: "var(--color-white)",
      transition: "left var(--duration-base) var(--ease-standard)"
    }
  })), label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: "var(--type-body-size)"
    }
  }, label));
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Switch.jsx", error: String((e && e.message) || e) }); }

// components/navigation/Tabs.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Tabs({
  items = [],
  value,
  defaultValue,
  onChange,
  style,
  ...rest
}) {
  const first = items.length ? typeof items[0] === "string" ? items[0] : items[0].value : undefined;
  const [internal, setInternal] = React.useState(defaultValue !== undefined ? defaultValue : first);
  const active = value === undefined ? internal : value;
  return /*#__PURE__*/React.createElement("div", _extends({
    role: "tablist",
    style: {
      display: "flex",
      alignItems: "center",
      gap: 4,
      borderBottom: "1px solid var(--border-default)",
      ...style
    }
  }, rest), items.map(function (it) {
    const t = typeof it === "string" ? {
      value: it,
      label: it
    } : it;
    const on = t.value === active;
    return /*#__PURE__*/React.createElement("button", {
      key: t.value,
      role: "tab",
      "aria-selected": on,
      onClick: function () {
        if (value === undefined) setInternal(t.value);
        if (onChange) onChange(t.value);
      },
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        height: 36,
        padding: "0 10px",
        border: 0,
        background: "transparent",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        fontSize: "var(--type-body-size)",
        color: on ? "var(--text-primary)" : "var(--text-muted)",
        borderBottom: "2px solid " + (on ? "var(--color-off-black)" : "transparent"),
        marginBottom: -1,
        transition: "color var(--duration-fast) linear"
      }
    }, t.label, t.count !== undefined && /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "var(--type-mono-size)",
        color: "var(--text-tertiary)"
      }
    }, t.count));
  }));
}
Object.assign(__ds_scope, { Tabs });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Tabs.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/AppChrome.jsx
try { (() => {
// Helpdesk app chrome: left icon rail, workspace header, section title bar.
const RAIL = [{
  id: "inbox",
  icon: "inbox",
  label: "Inbox",
  count: 12
}, {
  id: "reports",
  icon: "bar-chart-3",
  label: "Reports"
}, {
  id: "settings",
  icon: "settings",
  label: "Settings"
}];
function Rail({
  route,
  onRoute,
  onSignOut
}) {
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: 64,
      flex: "0 0 64px",
      background: "var(--surface-inverse)",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      padding: "16px 0",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 32,
      height: 32,
      borderRadius: "var(--radius-button)",
      background: "var(--color-fin)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "#fff",
      fontFamily: "var(--font-sans)",
      fontSize: 18,
      lineHeight: 1,
      marginBottom: 12
    }
  }, "W"), RAIL.map(r => {
    const on = route === r.id;
    return /*#__PURE__*/React.createElement(Tooltip, {
      key: r.id,
      content: r.label,
      placement: "bottom"
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => onRoute(r.id),
      "aria-label": r.label,
      style: {
        position: "relative",
        width: 40,
        height: 40,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "var(--radius-nav)",
        border: 0,
        cursor: "pointer",
        background: on ? "var(--color-black-80)" : "transparent"
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: r.icon,
      size: 20,
      color: on ? "#fff" : "var(--color-black-50)"
    }), r.count && /*#__PURE__*/React.createElement("span", {
      style: {
        position: "absolute",
        top: 4,
        right: 2,
        minWidth: 16,
        height: 16,
        padding: "0 4px",
        borderRadius: 999,
        background: "var(--color-fin)",
        color: "#fff",
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        lineHeight: "16px",
        textAlign: "center"
      }
    }, r.count)));
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "auto",
      display: "flex",
      flexDirection: "column",
      gap: 8,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement(Tooltip, {
    content: "Sign out",
    placement: "top"
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onSignOut,
    "aria-label": "Sign out",
    style: {
      width: 40,
      height: 40,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      borderRadius: "var(--radius-nav)",
      border: 0,
      background: "transparent",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "log-out",
    size: 18,
    color: "var(--color-black-50)"
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 999,
      background: "var(--color-sand)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "var(--font-sans)",
      fontSize: 12
    }
  }, "DO")));
}
function PanelHead({
  title,
  children,
  right
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: 56,
      flex: "0 0 56px",
      padding: "0 16px",
      display: "flex",
      alignItems: "center",
      gap: 12,
      borderBottom: "1px solid var(--border-default)",
      background: "var(--surface-primary)",
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 18,
      lineHeight: 1,
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis",
      minWidth: 0
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      flex: "0 0 auto"
    }
  }, children), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: 8,
      flex: "0 0 auto"
    }
  }, right));
}
function MonoLabel({
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      lineHeight: 1.3,
      letterSpacing: "1.2px",
      textTransform: "uppercase",
      color: "var(--text-tertiary)",
      ...style
    }
  }, children);
}
Object.assign(window, {
  Rail,
  PanelHead,
  MonoLabel
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/AppChrome.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/InboxScreen.jsx
try { (() => {
// Three-pane inbox: conversation list, thread with composer, customer details panel.
const CONVOS = [{
  id: 1,
  name: "Priya Raman",
  company: "Northwind",
  subject: "Charged twice for September",
  preview: "My invoice charged twice this month — can you refund one?",
  time: "2m",
  state: "open",
  ai: true,
  unread: true,
  msgs: [{
    from: "them",
    t: "Hi — my invoice charged twice this month. Can you refund one?",
    at: "09:41"
  }, {
    from: "fin",
    t: "I found two charges on 4 Sept for $49.00. I've refunded the duplicate — it should clear in 3–5 business days.",
    at: "09:41"
  }, {
    from: "them",
    t: "Thanks. Can someone confirm the annual plan wasn't affected?",
    at: "09:44"
  }]
}, {
  id: 2,
  name: "Tomás Lund",
  company: "Parcel",
  subject: "SSO setup for 40 seats",
  preview: "We're rolling out SAML this week and need…",
  time: "18m",
  state: "open",
  unread: true,
  msgs: [{
    from: "them",
    t: "We're rolling out SAML this week and need the metadata URL.",
    at: "09:12"
  }]
}, {
  id: 3,
  name: "Mei Fong",
  company: "Lumen",
  subject: "Fin gave a wrong refund window",
  preview: "It said 3 days, our policy is 10.",
  time: "1h",
  state: "waiting",
  ai: true,
  msgs: [{
    from: "them",
    t: "Fin told a customer 3 days; our policy is 10 business days.",
    at: "08:20"
  }]
}, {
  id: 4,
  name: "Alex Whitfield",
  company: "Hatchway",
  subject: "Exporting conversation history",
  preview: "Is there a CSV export with tags included?",
  time: "3h",
  state: "open",
  msgs: [{
    from: "them",
    t: "Is there a CSV export that includes tags?",
    at: "06:55"
  }]
}, {
  id: 5,
  name: "Sara Nowak",
  company: "Vela",
  subject: "Thanks for the quick fix",
  preview: "All sorted — appreciate it.",
  time: "Yesterday",
  state: "closed",
  msgs: [{
    from: "them",
    t: "All sorted — appreciate it.",
    at: "17:02"
  }]
}];
const FILTERS = [{
  value: "open",
  label: "Open",
  count: 12
}, {
  value: "waiting",
  label: "Waiting",
  count: 3
}, {
  value: "closed",
  label: "Closed"
}];
function ConvoRow({
  c,
  active,
  onClick
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: "block",
      width: "100%",
      textAlign: "left",
      padding: "14px 16px",
      border: 0,
      borderBottom: "1px solid var(--border-default)",
      cursor: "pointer",
      background: active ? "var(--surface-primary)" : hover ? "var(--color-white)" : "transparent",
      borderLeft: active ? "2px solid var(--color-off-black)" : "2px solid transparent"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 24,
      height: 24,
      borderRadius: 999,
      background: "var(--color-sand)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "var(--font-sans)",
      fontSize: 11
    }
  }, c.name.split(" ").map(n => n[0]).join("")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1
    }
  }, c.name), c.ai && /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: 999,
      background: "var(--color-fin)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      letterSpacing: "0.6px",
      color: "var(--text-tertiary)"
    }
  }, c.time)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      marginTop: 8,
      fontWeight: c.unread ? 400 : 300
    }
  }, c.subject), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)",
      marginTop: 4,
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap"
    }
  }, c.preview));
}
function Bubble({
  m
}) {
  const mine = m.from === "me";
  const fin = m.from === "fin";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: mine ? "flex-end" : "flex-start",
      gap: 6
    }
  }, fin && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: 999,
      background: "var(--color-fin)"
    }
  }), /*#__PURE__*/React.createElement(MonoLabel, {
    style: {
      color: "var(--color-fin)"
    }
  }, "Fin \xB7 AI agent")), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "72%",
      padding: "12px 14px",
      borderRadius: "var(--radius-card)",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1.5,
      background: mine ? "var(--surface-inverse)" : "var(--surface-card)",
      color: mine ? "var(--text-inverse)" : "var(--text-primary)",
      border: mine ? "1px solid var(--color-off-black)" : "1px solid var(--border-default)"
    }
  }, m.t), /*#__PURE__*/React.createElement(MonoLabel, {
    style: {
      fontSize: 11
    }
  }, m.at));
}
function DetailsPanel({
  c,
  onClose
}) {
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: 296,
      flex: "0 0 296px",
      borderLeft: "1px solid var(--border-default)",
      background: "var(--surface-page)",
      overflow: "auto"
    }
  }, /*#__PURE__*/React.createElement(PanelHead, {
    title: "Details",
    right: /*#__PURE__*/React.createElement(IconButton, {
      name: "panel-right-close",
      size: "sm",
      onClick: onClose,
      label: "Hide details"
    })
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 16,
      display: "flex",
      flexDirection: "column",
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 40,
      height: 40,
      borderRadius: 999,
      background: "var(--color-sand)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "var(--font-sans)",
      fontSize: 14
    }
  }, c.name.split(" ").map(n => n[0]).join("")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, c.name), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)"
    }
  }, c.company))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(MonoLabel, null, "Customer"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      display: "flex",
      flexDirection: "column",
      gap: 10
    }
  }, [["Plan", "Growth · yearly"], ["Seats", "42"], ["MRR", "$2,898"], ["Since", "Mar 2024"], ["Region", "EU (Frankfurt)"]].map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      display: "flex",
      justifyContent: "space-between",
      gap: 12,
      fontFamily: "var(--font-sans)",
      fontSize: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)",
      fontWeight: 300
    }
  }, k), /*#__PURE__*/React.createElement("span", null, v))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(MonoLabel, null, "Tags"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 8,
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(Tag, {
    selected: true
  }, "VIP"), /*#__PURE__*/React.createElement(Tag, {
    onRemove: () => {}
  }, "Billing"), /*#__PURE__*/React.createElement(Tag, {
    onRemove: () => {}
  }, "Refund"))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(MonoLabel, null, "Recent conversations"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, [["Invoice PDF missing", "Resolved by Fin"], ["Add seats mid-term", "Resolved by Dana"], ["Data residency question", "Resolved by Fin"]].map(([t, s]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      padding: 12,
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14
    }
  }, t), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)",
      marginTop: 4
    }
  }, s)))))));
}
function InboxScreen() {
  const [filter, setFilter] = React.useState("open");
  const [activeId, setActiveId] = React.useState(1);
  const [threads, setThreads] = React.useState(() => Object.fromEntries(CONVOS.map(c => [c.id, c.msgs])));
  const [draft, setDraft] = React.useState("");
  const [details, setDetails] = React.useState(true);
  const [toast, setToast] = React.useState(null);
  const [closing, setClosing] = React.useState(false);
  const list = CONVOS.filter(c => c.state === filter);
  const active = CONVOS.find(c => c.id === activeId) || list[0] || CONVOS[0];
  const msgs = threads[active.id] || [];
  const threadRef = React.useRef(null);
  React.useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [threads, activeId]);
  const send = () => {
    if (!draft.trim()) return;
    setThreads(t => ({
      ...t,
      [active.id]: [...(t[active.id] || []), {
        from: "me",
        t: draft.trim(),
        at: "09:47"
      }]
    }));
    setDraft("");
    setToast({
      tone: "success",
      title: "Reply sent",
      description: active.name + " will be notified by email."
    });
  };
  const finDraft = () => setDraft("Confirmed — your annual plan is untouched. Only the duplicate $49.00 charge from 4 Sept was refunded, and it will clear in 3–5 business days.");
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flex: 1,
      minWidth: 0,
      height: "100vh",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("section", {
    style: {
      width: 320,
      flex: "0 0 320px",
      borderRight: "1px solid var(--border-default)",
      display: "flex",
      flexDirection: "column",
      background: "var(--surface-page)"
    }
  }, /*#__PURE__*/React.createElement(PanelHead, {
    title: "Inbox",
    right: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(IconButton, {
      name: "filter",
      size: "sm",
      label: "Filter"
    }), /*#__PURE__*/React.createElement(IconButton, {
      name: "pen-line",
      size: "sm",
      variant: "solid",
      label: "New conversation"
    }))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "12px 16px",
      borderBottom: "1px solid var(--border-default)",
      background: "var(--surface-primary)"
    }
  }, /*#__PURE__*/React.createElement(Input, {
    size: "sm",
    iconLeft: "search",
    placeholder: "Search conversations"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "0 16px",
      background: "var(--surface-primary)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement(Tabs, {
    items: FILTERS,
    value: filter,
    onChange: v => {
      setFilter(v);
      const first = CONVOS.find(c => c.state === v);
      if (first) setActiveId(first.id);
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      overflow: "auto",
      flex: 1
    }
  }, list.map(c => /*#__PURE__*/React.createElement(ConvoRow, {
    key: c.id,
    c: c,
    active: c.id === active.id,
    onClick: () => setActiveId(c.id)
  })), !list.length && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 24,
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)"
    }
  }, "Nothing here. Nice."))), /*#__PURE__*/React.createElement("section", {
    style: {
      flex: 1,
      minWidth: 380,
      display: "flex",
      flexDirection: "column",
      background: "var(--surface-primary)"
    }
  }, /*#__PURE__*/React.createElement(PanelHead, {
    title: active.subject,
    children: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Badge, {
      tone: active.state === "closed" ? "neutral" : active.state === "waiting" ? "info" : "success"
    }, active.state), active.ai && /*#__PURE__*/React.createElement(Badge, {
      tone: "accent"
    }, "Fin handled")),
    right: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Select, {
      size: "sm",
      options: ["Assign to Dana", "Assign to Mira", "Assign to Fin"]
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "outlined",
      onClick: () => setClosing(true)
    }, "Close"), !details && /*#__PURE__*/React.createElement(IconButton, {
      name: "panel-right-open",
      size: "sm",
      onClick: () => setDetails(true),
      label: "Show details"
    }))
  }), /*#__PURE__*/React.createElement("div", {
    ref: threadRef,
    style: {
      flex: 1,
      overflow: "auto",
      padding: 24,
      display: "flex",
      flexDirection: "column",
      gap: 20,
      background: "var(--surface-primary)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 1,
      background: "var(--border-default)"
    }
  }), /*#__PURE__*/React.createElement(MonoLabel, null, "Today"), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 1,
      background: "var(--border-default)"
    }
  })), msgs.map((m, i) => /*#__PURE__*/React.createElement(Bubble, {
    key: i,
    m: m
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      borderTop: "1px solid var(--border-default)",
      padding: 16,
      background: "var(--surface-page)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      background: "var(--surface-primary)"
    }
  }, /*#__PURE__*/React.createElement("textarea", {
    value: draft,
    onChange: e => setDraft(e.target.value),
    placeholder: "Write a reply\u2026  \u2318\u21B5 to send",
    style: {
      width: "100%",
      minHeight: 84,
      resize: "none",
      border: 0,
      outline: "none",
      background: "transparent",
      padding: 14,
      boxSizing: "border-box",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1.5,
      color: "var(--text-primary)"
    },
    onKeyDown: e => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      padding: "10px 12px",
      borderTop: "1px solid var(--border-default)",
      minWidth: 0,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement(IconButton, {
    name: "paperclip",
    size: "sm",
    label: "Attach"
  }), /*#__PURE__*/React.createElement(IconButton, {
    name: "smile",
    size: "sm",
    label: "Emoji"
  }), /*#__PURE__*/React.createElement(IconButton, {
    name: "zap",
    size: "sm",
    label: "Macros"
  }), /*#__PURE__*/React.createElement(Button, {
    size: "sm",
    variant: "accent",
    onClick: finDraft
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles",
    size: 14
  }), " Draft with Fin"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(MonoLabel, null, "Public reply"), /*#__PURE__*/React.createElement(Button, {
    size: "sm",
    onClick: send
  }, "Send")))))), details && /*#__PURE__*/React.createElement(DetailsPanel, {
    c: active,
    onClose: () => setDetails(false)
  }), /*#__PURE__*/React.createElement(Dialog, {
    open: closing,
    title: "Close this conversation?",
    description: "Fin will keep learning from it. The customer can reopen by replying.",
    onClose: () => setClosing(false),
    footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      onClick: () => setClosing(false)
    }, "Cancel"), /*#__PURE__*/React.createElement(Button, {
      onClick: () => {
        setClosing(false);
        setToast({
          tone: "neutral",
          title: "Conversation closed",
          description: active.subject
        });
      }
    }, "Close conversation"))
  }), toast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "fixed",
      bottom: 20,
      left: 84,
      zIndex: 60
    }
  }, /*#__PURE__*/React.createElement(Toast, {
    tone: toast.tone,
    title: toast.title,
    description: toast.description,
    onDismiss: () => setToast(null)
  })));
}
Object.assign(window, {
  InboxScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/InboxScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/LoginScreen.jsx
try { (() => {
// Sign-in screen: warm-cream canvas, single card, real form primitives.
function LoginScreen({
  onSignIn
}) {
  const [email, setEmail] = React.useState("dana@northwind.com");
  const [pw, setPw] = React.useState("");
  const [remember, setRemember] = React.useState(true);
  const [err, setErr] = React.useState("");
  const submit = e => {
    e.preventDefault();
    if (!pw) {
      setErr("Enter your password to continue.");
      return;
    }
    onSignIn();
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: "100vh",
      background: "var(--surface-page)",
      display: "grid",
      gridTemplateColumns: "1fr 1fr"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: 40
    }
  }, /*#__PURE__*/React.createElement("form", {
    onSubmit: submit,
    style: {
      width: 380,
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 32
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 24,
      lineHeight: 1,
      letterSpacing: "-0.48px"
    }
  }, "Warmline"), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "24px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 40,
      lineHeight: 1,
      letterSpacing: "-1.2px",
      fontWeight: 400
    }
  }, "Sign in"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 16,
      marginTop: 24
    }
  }, /*#__PURE__*/React.createElement(Input, {
    label: "Work email",
    iconLeft: "mail",
    value: email,
    onChange: e => setEmail(e.target.value)
  }), /*#__PURE__*/React.createElement(Input, {
    label: "Password",
    type: "password",
    placeholder: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022",
    value: pw,
    error: err,
    onChange: e => {
      setPw(e.target.value);
      setErr("");
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement(Checkbox, {
    label: "Keep me signed in",
    checked: remember,
    onChange: setRemember
  }), /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-secondary)"
    }
  }, "Forgot?")), /*#__PURE__*/React.createElement(Button, {
    type: "submit",
    fullWidth: true,
    size: "lg"
  }, "Sign in"), /*#__PURE__*/React.createElement(Button, {
    variant: "outlined",
    fullWidth: true
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "key-round",
    size: 16
  }), " Continue with SSO")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 24,
      paddingTop: 20,
      borderTop: "1px solid var(--border-default)",
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)"
    }
  }, "New here? ", /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault()
  }, "Start a free trial")))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-inverse)",
      color: "var(--text-inverse)",
      padding: 60,
      display: "flex",
      flexDirection: "column",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement(MonoLabel, {
    style: {
      color: "var(--color-sand)"
    }
  }, "This week in your workspace"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 24,
      marginTop: 32
    }
  }, [["1,482", "conversations", "var(--color-report-blue)"], ["65%", "resolved by Fin", "var(--color-report-green)"], ["1.2s", "median first reply", "var(--color-report-lime)"], ["4.8", "CSAT", "var(--color-report-pink)"]].map(([v, l, c]) => /*#__PURE__*/React.createElement("div", {
    key: l
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 54,
      lineHeight: 1,
      letterSpacing: "-1.6px"
    }
  }, v), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 4,
      background: c,
      borderRadius: 2,
      margin: "12px 0"
    }
  }), /*#__PURE__*/React.createElement(MonoLabel, {
    style: {
      color: "var(--color-black-50)"
    }
  }, l))))));
}
Object.assign(window, {
  LoginScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/LoginScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/ReportsScreen.jsx
try { (() => {
// Reports: KPI row, stacked volume chart, topic table — the report palette in use.
const WEEK = [{
  d: "Mon",
  fin: 148,
  team: 62
}, {
  d: "Tue",
  fin: 172,
  team: 58
}, {
  d: "Wed",
  fin: 190,
  team: 71
}, {
  d: "Thu",
  fin: 164,
  team: 49
}, {
  d: "Fri",
  fin: 205,
  team: 66
}, {
  d: "Sat",
  fin: 96,
  team: 12
}, {
  d: "Sun",
  fin: 88,
  team: 9
}];
const TOPICS = [["Billing & invoices", 412, "68%", "var(--color-report-green)"], ["Login & SSO", 268, "54%", "var(--color-report-blue)"], ["Shipping status", 221, "81%", "var(--color-report-lime)"], ["Refund policy", 174, "37%", "var(--color-report-orange)"], ["Bug reports", 131, "12%", "var(--color-report-pink)"]];
function ReportsScreen() {
  const [range, setRange] = React.useState("7d");
  const max = Math.max(...WEEK.map(w => w.fin + w.team));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      height: "100vh",
      overflow: "auto",
      background: "var(--surface-page)"
    }
  }, /*#__PURE__*/React.createElement(PanelHead, {
    title: "Reports",
    right: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Tabs, {
      items: [{
        value: "7d",
        label: "7 days"
      }, {
        value: "30d",
        label: "30 days"
      }, {
        value: "qtr",
        label: "Quarter"
      }],
      value: range,
      onChange: setRange
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "outlined"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "download",
      size: 14
    }), " Export"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 24,
      display: "flex",
      flexDirection: "column",
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 16
    }
  }, [["Conversations", "1,482", "+8.2%", "var(--color-report-blue)"], ["Resolved by Fin", "65%", "+4.1pt", "var(--color-report-green)"], ["Median first reply", "1.2s", "-0.3s", "var(--color-report-lime)"], ["CSAT", "4.8", "+0.1", "var(--color-report-pink)"]].map(([l, v, d, c]) => /*#__PURE__*/React.createElement(Card, {
    key: l,
    padding: 20,
    tone: "white"
  }, /*#__PURE__*/React.createElement(MonoLabel, null, l), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-end",
      gap: 10,
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 40,
      lineHeight: 1,
      letterSpacing: "-1.2px"
    }
  }, v), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      letterSpacing: "0.6px",
      color: "var(--text-muted)",
      paddingBottom: 4
    }
  }, d)), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 4,
      borderRadius: 2,
      background: c,
      marginTop: 16
    }
  })))), /*#__PURE__*/React.createElement(Card, {
    padding: 24,
    tone: "white"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement(MonoLabel, null, "Volume by day"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 16
    }
  }, [["Fin", "var(--color-fin)"], ["Team", "var(--color-off-black)"]].map(([l, c]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      background: c,
      borderRadius: 2
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-secondary)"
    }
  }, l))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(7, 1fr)",
      gap: 16,
      alignItems: "end",
      height: 200,
      marginTop: 24
    }
  }, WEEK.map(w => /*#__PURE__*/React.createElement("div", {
    key: w.d,
    style: {
      display: "flex",
      flexDirection: "column",
      justifyContent: "flex-end",
      gap: 2,
      height: "100%"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: `${w.team / max * 100}%`,
      background: "var(--color-off-black)",
      borderRadius: "2px 2px 0 0"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      height: `${w.fin / max * 100}%`,
      background: "var(--color-fin)",
      borderRadius: "0 0 2px 2px"
    }
  }), /*#__PURE__*/React.createElement(MonoLabel, {
    style: {
      textAlign: "center",
      marginTop: 8
    }
  }, w.d))))), /*#__PURE__*/React.createElement(Card, {
    padding: 0,
    tone: "white"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px 24px",
      borderBottom: "1px solid var(--border-default)",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement(MonoLabel, null, "Top topics"), /*#__PURE__*/React.createElement(Select, {
    size: "sm",
    options: ["Sorted by volume", "Sorted by resolution rate"]
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "2fr 1fr 1fr 2fr",
      padding: "12px 24px",
      borderBottom: "1px solid var(--border-default)"
    }
  }, ["Topic", "Volume", "Fin resolved", ""].map(h => /*#__PURE__*/React.createElement(MonoLabel, {
    key: h
  }, h))), TOPICS.map(([t, v, r, c]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      display: "grid",
      gridTemplateColumns: "2fr 1fr 1fr 2fr",
      padding: "16px 24px",
      borderBottom: "1px solid var(--border-default)",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, t), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      color: "var(--text-secondary)"
    }
  }, v), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      color: "var(--text-secondary)"
    }
  }, r), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 6,
      background: "var(--surface-card)",
      borderRadius: 3,
      border: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: r,
      height: "100%",
      background: c,
      borderRadius: 3
    }
  })))))));
}
Object.assign(window, {
  ReportsScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/ReportsScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/SettingsScreen.jsx
try { (() => {
// Settings: section nav, Fin configuration form, danger zone dialog.
function SettingsScreen() {
  const [section, setSection] = React.useState("fin");
  const [tone, setTone] = React.useState("Warm and brief");
  const [handover, setHandover] = React.useState(true);
  const [actions, setActions] = React.useState(true);
  const [langs, setLangs] = React.useState(["English", "German"]);
  const [confidence, setConfidence] = React.useState("balanced");
  const [saved, setSaved] = React.useState(false);
  const [reset, setReset] = React.useState(false);
  const NAV = [["fin", "Fin AI agent"], ["inbox", "Inbox"], ["team", "Teammates"], ["channels", "Channels"], ["security", "Security"]];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      height: "100vh",
      overflow: "auto",
      background: "var(--surface-page)"
    }
  }, /*#__PURE__*/React.createElement(PanelHead, {
    title: "Settings",
    right: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      onClick: () => setReset(true)
    }, "Reset defaults"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      onClick: () => setSaved(true)
    }, "Save changes"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "232px 1fr",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement("nav", {
    style: {
      padding: 16,
      borderRight: "1px solid var(--border-default)",
      display: "flex",
      flexDirection: "column",
      gap: 4,
      position: "sticky",
      top: 0
    }
  }, NAV.map(([id, label]) => /*#__PURE__*/React.createElement("button", {
    key: id,
    onClick: () => setSection(id),
    style: {
      textAlign: "left",
      padding: "10px 12px",
      borderRadius: "var(--radius-nav)",
      border: 0,
      cursor: "pointer",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      background: section === id ? "var(--surface-inverse)" : "transparent",
      color: section === id ? "var(--text-inverse)" : "var(--text-secondary)"
    }
  }, label))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 24,
      maxWidth: 720,
      display: "flex",
      flexDirection: "column",
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: 40,
      lineHeight: 1,
      letterSpacing: "-1.2px",
      fontWeight: 400
    }
  }, "Fin AI agent"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "16px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1.5,
      color: "var(--text-secondary)"
    }
  }, "Controls how Fin answers before a teammate sees the conversation.")), /*#__PURE__*/React.createElement(Card, {
    padding: 24,
    tone: "white"
  }, /*#__PURE__*/React.createElement(MonoLabel, null, "Voice"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 16,
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Select, {
    label: "Answer tone",
    options: ["Warm and brief", "Neutral and precise", "Formal"],
    value: tone,
    onChange: e => setTone(e.target.value)
  }), /*#__PURE__*/React.createElement(Input, {
    label: "Signature",
    defaultValue: "\u2014 Fin, Warmline Support"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Input, {
    label: "Escalation message",
    hint: "Sent when Fin hands over to a teammate.",
    defaultValue: "Let me bring in a teammate who can help with this."
  }))), /*#__PURE__*/React.createElement(Card, {
    padding: 24,
    tone: "white"
  }, /*#__PURE__*/React.createElement(MonoLabel, null, "Confidence threshold"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12,
      marginTop: 16
    }
  }, [["cautious", "Cautious — answer only with a cited source"], ["balanced", "Balanced — answer when confident, hand over otherwise"], ["assertive", "Assertive — attempt every conversation"]].map(([v, l]) => /*#__PURE__*/React.createElement(Radio, {
    key: v,
    name: "confidence",
    value: v,
    label: l,
    checked: confidence === v,
    onChange: () => setConfidence(v)
  })))), /*#__PURE__*/React.createElement(Card, {
    padding: 24,
    tone: "white"
  }, /*#__PURE__*/React.createElement(MonoLabel, null, "Behaviour"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 16,
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Switch, {
    label: "Hand over to a teammate on low confidence",
    checked: handover,
    onChange: setHandover
  }), /*#__PURE__*/React.createElement(Switch, {
    label: "Allow Fin to take actions (refunds, plan changes)",
    checked: actions,
    onChange: setActions
  }), /*#__PURE__*/React.createElement(Switch, {
    label: "Answer outside business hours only",
    checked: false,
    onChange: () => {},
    disabled: true
  }))), /*#__PURE__*/React.createElement(Card, {
    padding: 24,
    tone: "white"
  }, /*#__PURE__*/React.createElement(MonoLabel, null, "Languages"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 12,
      marginTop: 16
    }
  }, ["English", "German", "French", "Japanese", "Portuguese", "Korean"].map(l => /*#__PURE__*/React.createElement(Checkbox, {
    key: l,
    label: l,
    checked: langs.includes(l),
    onChange: on => setLangs(s => on ? [...s, l] : s.filter(x => x !== l))
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 20,
      paddingTop: 20,
      borderTop: "1px solid var(--border-default)"
    }
  }, langs.map(l => /*#__PURE__*/React.createElement(Tag, {
    key: l,
    selected: true,
    onRemove: () => setLangs(s => s.filter(x => x !== l))
  }, l)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "flex-end",
      gap: 12,
      paddingBottom: 40
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "outlined"
  }, "Preview answers"), /*#__PURE__*/React.createElement(Button, {
    onClick: () => setSaved(true)
  }, "Save changes")))), /*#__PURE__*/React.createElement(Dialog, {
    open: reset,
    title: "Reset Fin to defaults?",
    description: "Tone, threshold and language settings return to the Warmline defaults. Content sources are untouched.",
    onClose: () => setReset(false),
    footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      onClick: () => setReset(false)
    }, "Cancel"), /*#__PURE__*/React.createElement(Button, {
      onClick: () => {
        setReset(false);
        setSaved(true);
      }
    }, "Reset"))
  }), saved && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "fixed",
      bottom: 20,
      left: 84,
      zIndex: 60
    }
  }, /*#__PURE__*/React.createElement(Toast, {
    tone: "success",
    title: "Settings saved",
    description: "Fin is using the new configuration.",
    onDismiss: () => setSaved(false)
  })));
}
Object.assign(window, {
  SettingsScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/SettingsScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/ds-boot.js
try { (() => {
// Kit bootstrap: exposes the design-system namespace as globals for the screen files, and
// backfills any component the on-disk bundle is missing by compiling it from source
// (the bundle is regenerated between turns, so a freshly edited component can lag).
// Sets window.__dsReady — mount scripts await it before rendering.
(() => {
  const NS_KEY = "WarmlineDesignSystem_273f7f";
  const BASE = "../../";
  const SOURCES = {
    Icon: "components/core/Icon.jsx",
    Card: "components/core/Card.jsx",
    Badge: "components/core/Badge.jsx",
    Tag: "components/core/Tag.jsx",
    Button: "components/core/Button.jsx",
    IconButton: "components/core/IconButton.jsx",
    Input: "components/forms/Input.jsx",
    Select: "components/forms/Select.jsx",
    Checkbox: "components/forms/Checkbox.jsx",
    Radio: "components/forms/Radio.jsx",
    Switch: "components/forms/Switch.jsx",
    Tabs: "components/navigation/Tabs.jsx",
    Dialog: "components/feedback/Dialog.jsx",
    Toast: "components/feedback/Toast.jsx",
    Tooltip: "components/feedback/Tooltip.jsx"
  };
  window.__dsReady = (async () => {
    const ns = window[NS_KEY] || (window[NS_KEY] = {});
    const missing = Object.keys(SOURCES).filter(n => typeof ns[n] !== "function");
    if (missing.length) {
      const mods = {};
      const req = spec => spec === "react" ? window.React : mods[spec.split("/").pop().replace(/\.jsx?$/, "")] || {};
      for (const name of Object.keys(SOURCES)) {
        const src = await (await fetch(BASE + SOURCES[name])).text();
        const code = Babel.transform(src, {
          presets: ["react"],
          plugins: [["transform-modules-commonjs", {
            strictMode: false
          }]]
        }).code;
        const mod = {
          exports: {}
        };
        new Function("module", "exports", "require", code)(mod, mod.exports, req);
        mods[name] = mod.exports;
        ns[name] = mod.exports[name];
      }
      console.info("[ds-boot] compiled " + Object.keys(SOURCES).length + " components from source (bundle missing: " + missing.join(", ") + ")");
    }
    Object.assign(window, ns);
  })();
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/ds-boot.js", error: String((e && e.message) || e) }); }

// ui_kits/marketing/ArticleScreen.jsx
try { (() => {
// Editorial blog article: mono metadata, serif body, pull quote, subscribe band.
function ArticleScreen() {
  return /*#__PURE__*/React.createElement("main", {
    style: {
      background: "var(--surface-primary)"
    }
  }, /*#__PURE__*/React.createElement("article", {
    style: {
      maxWidth: 760,
      margin: "0 auto",
      padding: "80px 40px 40px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 16,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    color: "var(--color-fin)"
  }, "AI in support"), /*#__PURE__*/React.createElement(Eyebrow, null, "8 min read \xB7 2 Sept 2026")), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "24px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 54,
      lineHeight: 1,
      letterSpacing: "-1.6px",
      fontWeight: 400
    }
  }, "The deflection metric is lying to you"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "24px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 20,
      lineHeight: 0.95,
      letterSpacing: "-0.2px",
      color: "var(--text-secondary)"
    }
  }, "Every helpdesk vendor reports deflection. Almost none of them report whether the customer got what they wanted."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      margin: "32px 0",
      padding: "20px 0",
      borderTop: "1px solid var(--border-default)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      borderRadius: 999,
      background: "var(--surface-subtle)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "var(--font-sans)",
      fontSize: 14
    }
  }, "MR"), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, "Mira Reyes"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)"
    }
  }, "Support Research, Warmline")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(IconButton, {
    name: "link",
    variant: "outlined",
    size: "sm"
  }), /*#__PURE__*/React.createElement(IconButton, {
    name: "bookmark",
    variant: "outlined",
    size: "sm"
  }))), ["A deflected conversation is one that never reached a human. That is all it means. It does not mean the question was answered, and it certainly does not mean the customer left satisfied — a customer who gives up is deflected too.", "We looked at 1.4 million conversations across teams running an AI agent in front of their inbox. When we split deflection into resolved and abandoned, a third of what teams counted as a win was a customer walking away."].map((p, i) => /*#__PURE__*/React.createElement("p", {
    key: i,
    style: {
      margin: "0 0 20px",
      fontFamily: "var(--font-serif)",
      fontSize: 20,
      fontWeight: 300,
      lineHeight: 1.5,
      letterSpacing: "-0.16px",
      textWrap: "pretty"
    }
  }, p)), /*#__PURE__*/React.createElement("blockquote", {
    style: {
      margin: "40px 0",
      padding: "24px 0 24px 24px",
      borderLeft: "2px solid var(--color-fin)"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: 32,
      lineHeight: 1,
      letterSpacing: "-0.96px"
    }
  }, "Measure resolution, or measure nothing.")), /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: "0 0 20px",
      fontFamily: "var(--font-sans)",
      fontSize: 32,
      lineHeight: 1,
      letterSpacing: "-0.96px",
      fontWeight: 400
    }
  }, "What to track instead"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "0 0 20px",
      fontFamily: "var(--font-serif)",
      fontSize: 20,
      fontWeight: 300,
      lineHeight: 1.5,
      letterSpacing: "-0.16px"
    }
  }, "Three numbers survive scrutiny: resolution rate, reopen rate within seven days, and CSAT on AI-only conversations. Track them together and the picture stops flattering you."), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-card)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 20,
      margin: "32px 0"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "Benchmark, Q3 2026"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3, 1fr)",
      gap: 20,
      marginTop: 16
    }
  }, [["Resolution", "65%", "var(--color-report-green)"], ["Reopen", "6%", "var(--color-report-orange)"], ["CSAT (AI only)", "4.6", "var(--color-report-blue)"]].map(([l, v, c]) => /*#__PURE__*/React.createElement("div", {
    key: l
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 32,
      lineHeight: 1,
      letterSpacing: "-0.96px"
    }
  }, v), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 4,
      background: c,
      borderRadius: 2,
      margin: "12px 0"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)"
    }
  }, l))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement(Tag, null, "Reporting"), /*#__PURE__*/React.createElement(Tag, null, "Fin"), /*#__PURE__*/React.createElement(Tag, null, "Benchmarks"))), /*#__PURE__*/React.createElement("section", {
    style: {
      borderTop: "1px solid var(--border-default)",
      background: "var(--surface-page)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 760,
      margin: "0 auto",
      padding: "60px 40px",
      display: "flex",
      gap: 40,
      alignItems: "flex-end"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: 40,
      lineHeight: 1,
      letterSpacing: "-1.2px",
      fontWeight: 400
    }
  }, "One good support read, monthly."), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "16px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1.5,
      color: "var(--text-secondary)"
    }
  }, "No product news. No webinars.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 10,
      flex: "0 0 320px"
    }
  }, /*#__PURE__*/React.createElement(Input, {
    placeholder: "you@company.com",
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(Button, null, "Subscribe")))));
}
Object.assign(window, {
  ArticleScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/ArticleScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/Chrome.jsx
try { (() => {
// Marketing site chrome: top nav, section helpers, footer, CTA band.
const NAV = ["Product", "Solutions", "Pricing", "Docs", "Blog"];
function Wordmark({
  size = 22,
  color = "var(--text-primary)"
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: size,
      lineHeight: 1,
      letterSpacing: size * -0.03,
      color,
      whiteSpace: "nowrap"
    }
  }, "Warmline");
}
function Eyebrow({
  children,
  color = "var(--text-muted)",
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      lineHeight: 1.3,
      letterSpacing: "1.2px",
      textTransform: "uppercase",
      color,
      ...style
    }
  }, children);
}
function Nav({
  route,
  onRoute
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      position: "sticky",
      top: 0,
      zIndex: 20,
      background: "var(--surface-primary)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "0 40px",
      height: 64,
      display: "flex",
      alignItems: "center",
      gap: 40
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => {
      e.preventDefault();
      onRoute("home");
    },
    style: {
      textDecoration: "none"
    }
  }, /*#__PURE__*/React.createElement(Wordmark, null)), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 24,
      flex: 1
    }
  }, NAV.map(n => {
    const key = n.toLowerCase();
    const on = route === key || key === "product" && route === "product";
    return /*#__PURE__*/React.createElement("a", {
      key: n,
      href: "#",
      onClick: e => {
        e.preventDefault();
        onRoute(key === "blog" ? "article" : key);
      },
      style: {
        fontFamily: "var(--font-sans)",
        fontSize: 16,
        lineHeight: 1,
        color: on ? "var(--text-primary)" : "var(--text-secondary)",
        textDecoration: "none",
        display: "flex",
        alignItems: "center",
        gap: 6
      }
    }, n, n === "Solutions" && /*#__PURE__*/React.createElement(Icon, {
      name: "chevron-down",
      size: 14,
      color: "var(--text-tertiary)"
    }));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm"
  }, "Sign in"), /*#__PURE__*/React.createElement(Button, {
    size: "sm"
  }, "Start free trial"))));
}
function LogoStrip() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      borderTop: "1px solid var(--border-default)",
      borderBottom: "1px solid var(--border-default)",
      background: "var(--surface-primary)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "24px 40px",
      display: "flex",
      alignItems: "center",
      gap: 40
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      flex: "0 0 auto"
    }
  }, "Trusted by 25,000+ teams"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 40,
      flex: 1,
      justifyContent: "flex-end",
      alignItems: "center"
    }
  }, ["Northwind", "Lumen", "Parcel", "Hatchway", "Vela", "Orbit"].map(c => /*#__PURE__*/React.createElement("div", {
    key: c,
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 20,
      letterSpacing: "-0.4px",
      color: "var(--color-black-50)"
    }
  }, c)))));
}
function CtaBand() {
  return /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--surface-inverse)",
      color: "var(--text-inverse)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "96px 40px",
      display: "flex",
      alignItems: "flex-end",
      justifyContent: "space-between",
      gap: 60
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 640
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    color: "var(--color-sand)"
  }, "Get started"), /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: "20px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 54,
      lineHeight: 1,
      letterSpacing: "-1.6px",
      fontWeight: 400
    }
  }, "Turn support into your fastest team.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 12,
      flex: "0 0 auto"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "warm"
  }, "Start free trial"), /*#__PURE__*/React.createElement(Button, {
    variant: "outlined",
    style: {
      color: "var(--text-inverse)",
      borderColor: "var(--color-black-60)"
    }
  }, "Book a demo"))));
}
function Footer() {
  const cols = [["Product", ["AI agent", "Inbox", "Help center", "Reports", "Integrations"]], ["Solutions", ["Support teams", "Startups", "E-commerce", "Financial services"]], ["Resources", ["Docs", "Changelog", "Community", "Status"]], ["Company", ["About", "Careers", "Security", "Contact"]]];
  return /*#__PURE__*/React.createElement("footer", {
    style: {
      background: "var(--surface-primary)",
      borderTop: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "60px 40px 32px",
      display: "grid",
      gridTemplateColumns: "1.4fr repeat(4, 1fr)",
      gap: 40
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Wordmark, {
    size: 24
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "16px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      lineHeight: 1.4,
      color: "var(--text-muted)",
      maxWidth: 240
    }
  }, "The customer service platform with an AI agent at the front.")), cols.map(([label, links]) => /*#__PURE__*/React.createElement("div", {
    key: label
  }, /*#__PURE__*/React.createElement(Eyebrow, null, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 10,
      marginTop: 16
    }
  }, links.map(l => /*#__PURE__*/React.createElement("a", {
    key: l,
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-secondary)",
      textDecoration: "none"
    }
  }, l)))))), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "20px 40px 40px",
      borderTop: "1px solid var(--border-default)",
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "\xA9 2026 Warmline"), /*#__PURE__*/React.createElement(Eyebrow, null, "Privacy \xB7 Terms \xB7 Cookies")));
}
Object.assign(window, {
  Wordmark,
  Eyebrow,
  Nav,
  LogoStrip,
  CtaBand,
  Footer
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/Chrome.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/HomeScreen.jsx
try { (() => {
// Marketing homepage: hero, trust strip, metric band, feature grid, editorial quote.
const HOME_FEATURES = [{
  icon: "sparkles",
  title: "Fin answers instantly",
  body: "An AI agent trained on your help center, macros and past conversations — live in a day, not a quarter.",
  accent: true
}, {
  icon: "inbox",
  title: "One desk for the rest",
  body: "Email, chat, phone and social land in a single inbox with the context your team already trusts."
}, {
  icon: "bar-chart-3",
  title: "Reporting you'll read",
  body: "Resolution rate, first reply, CSAT and cost per conversation — in one view, no spreadsheet."
}];
const HOME_STATS = [["65%", "resolved instantly"], ["1.2s", "median first reply"], ["45", "languages"], ["24/7", "coverage"]];
function HomeScreen({
  onRoute
}) {
  return /*#__PURE__*/React.createElement("main", null, /*#__PURE__*/React.createElement("section", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "80px 40px 60px",
      display: "grid",
      gridTemplateColumns: "1.15fr 0.85fr",
      gap: 60,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Eyebrow, null, "AI-first customer service"), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "24px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 80,
      lineHeight: 1,
      letterSpacing: "-2.4px",
      fontWeight: 400
    }
  }, "Support that answers before you do."), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "24px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 20,
      lineHeight: 0.95,
      letterSpacing: "-0.2px",
      color: "var(--text-secondary)",
      maxWidth: 520,
      textWrap: "pretty"
    }
  }, "Fin resolves the questions your team keeps repeating. Your people take the ones that matter."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 12,
      marginTop: 32
    }
  }, /*#__PURE__*/React.createElement(Button, {
    size: "lg"
  }, "Start free trial"), /*#__PURE__*/React.createElement(Button, {
    size: "lg",
    variant: "outlined",
    onClick: () => onRoute("product")
  }, "See how Fin works")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      marginTop: 20
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 14,
    color: "var(--text-muted)"
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)"
    }
  }, "14 days free \xB7 no card \xB7 cancel in one click"))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 8,
      height: 8,
      borderRadius: 999,
      background: "var(--color-fin)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, "Fin"), /*#__PURE__*/React.createElement(Badge, {
    tone: "accent"
  }, "AI")), /*#__PURE__*/React.createElement(Eyebrow, null, "Live")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12,
      marginTop: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      alignSelf: "flex-end",
      maxWidth: "78%",
      background: "var(--surface-inverse)",
      color: "var(--text-inverse)",
      borderRadius: "var(--radius-card)",
      padding: "12px 14px",
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      lineHeight: 1.4
    }
  }, "My invoice charged twice this month \u2014 can you refund one?"), /*#__PURE__*/React.createElement("div", {
    style: {
      alignSelf: "flex-start",
      maxWidth: "88%",
      background: "var(--surface-card)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: "12px 14px",
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      lineHeight: 1.4
    }
  }, "I found two charges on 4 Sept for $49. I've refunded the duplicate \u2014 it'll clear in 3\u20135 days. Here's the receipt."), /*#__PURE__*/React.createElement("div", {
    style: {
      alignSelf: "flex-start",
      display: "flex",
      alignItems: "center",
      gap: 8,
      paddingLeft: 2
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "file-text",
    size: 14,
    color: "var(--text-muted)"
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      letterSpacing: "0.6px",
      color: "var(--text-muted)"
    }
  }, "RECEIPT-4471.PDF"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 20,
      paddingTop: 16,
      borderTop: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement(Tag, {
    selected: true
  }, "Refunds"), /*#__PURE__*/React.createElement(Tag, null, "Billing"), /*#__PURE__*/React.createElement(Tag, null, "Resolved by Fin")))), /*#__PURE__*/React.createElement(LogoStrip, null), /*#__PURE__*/React.createElement("section", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "60px 40px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 24
    }
  }, HOME_STATS.map(([n, l]) => /*#__PURE__*/React.createElement("div", {
    key: l
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 54,
      lineHeight: 1,
      letterSpacing: "-1.6px"
    }
  }, n), /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      marginTop: 12
    }
  }, l))))), /*#__PURE__*/React.createElement("section", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "40px 40px 80px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: 54,
      lineHeight: 1,
      letterSpacing: "-1.6px",
      fontWeight: 400,
      maxWidth: 720
    }
  }, "Everything a support team runs on, in one place."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3, 1fr)",
      gap: 20,
      marginTop: 40
    }
  }, HOME_FEATURES.map(f => /*#__PURE__*/React.createElement(Card, {
    key: f.title,
    padding: 24,
    interactive: true
  }, /*#__PURE__*/React.createElement(Icon, {
    name: f.icon,
    size: 24,
    color: f.accent ? "var(--color-fin)" : "var(--text-primary)"
  }), /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: "60px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 32,
      lineHeight: 1,
      letterSpacing: "-0.96px",
      fontWeight: 400
    }
  }, f.title), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "16px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1.5,
      color: "var(--text-secondary)",
      textWrap: "pretty"
    }
  }, f.body), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6,
      marginTop: 24,
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, "Learn more ", /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-right",
    size: 16
  })))))), /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--surface-primary)",
      borderTop: "1px solid var(--border-default)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "80px 40px",
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 80,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("blockquote", {
    style: {
      margin: 0
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontFamily: "var(--font-serif)",
      fontSize: 40,
      lineHeight: 1.1,
      letterSpacing: "-1.2px",
      fontWeight: 300,
      textWrap: "pretty"
    }
  }, "\u201CWe cut first-response time from four hours to under two seconds, and nobody on the team works a weekend anymore.\u201D"), /*#__PURE__*/React.createElement("footer", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      marginTop: 32
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, "Dana Okoye"), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 16,
      background: "var(--border-default)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      color: "var(--text-muted)"
    }
  }, "Head of Support, Northwind"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 16
    }
  }, [["Resolution rate", "65%", "var(--color-report-green)"], ["Cost per conversation", "-42%", "var(--color-report-blue)"], ["CSAT", "4.8", "var(--color-report-lime)"], ["Backlog", "-71%", "var(--color-report-pink)"]].map(([l, v, c]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    style: {
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 20,
      background: "var(--surface-card)"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 40,
      lineHeight: 1,
      letterSpacing: "-1.2px",
      marginTop: 16
    }
  }, v), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 4,
      borderRadius: 2,
      background: c,
      marginTop: 16
    }
  })))))), /*#__PURE__*/React.createElement(CtaBand, null));
}
Object.assign(window, {
  HomeScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/HomeScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/PricingScreen.jsx
try { (() => {
// Pricing page: term switch, three plans, comparison rows, FAQ.
const PLANS = [{
  name: "Essential",
  price: [39, 29],
  blurb: "For small teams getting off email.",
  features: ["Shared inbox", "Help center", "2 seats included", "Email + chat"],
  cta: "Start free trial",
  variant: "outlined"
}, {
  name: "Growth",
  price: [85, 69],
  blurb: "For teams running Fin in production.",
  features: ["Everything in Essential", "Fin AI agent", "SAML SSO", "Custom reporting", "Workflows"],
  cta: "Start free trial",
  variant: "primary",
  featured: true
}, {
  name: "Enterprise",
  price: null,
  blurb: "For regulated and high-volume support.",
  features: ["Everything in Growth", "Dedicated region", "Audit log + HIPAA", "Named CSM"],
  cta: "Talk to sales",
  variant: "warm"
}];
const ROWS = [["Conversations / month", "1,000", "Unlimited", "Unlimited"], ["Fin resolutions", "—", "Pay per resolution", "Committed volume"], ["Languages", "8", "45", "45"], ["Support SLA", "Business hours", "24/5", "24/7 + phone"]];
function PricingScreen() {
  const [yearly, setYearly] = React.useState(true);
  return /*#__PURE__*/React.createElement("main", null, /*#__PURE__*/React.createElement("section", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "80px 40px 40px",
      textAlign: "center"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      display: "flex",
      justifyContent: "center"
    }
  }, "Pricing"), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "24px auto 0",
      fontFamily: "var(--font-sans)",
      fontSize: 80,
      lineHeight: 1,
      letterSpacing: "-2.4px",
      fontWeight: 400,
      maxWidth: 800
    }
  }, "Pay per seat. Pay per resolution."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 14,
      marginTop: 32
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      color: yearly ? "var(--text-muted)" : "var(--text-primary)"
    }
  }, "Monthly"), /*#__PURE__*/React.createElement(Switch, {
    checked: yearly,
    onChange: setYearly
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      color: yearly ? "var(--text-primary)" : "var(--text-muted)"
    }
  }, "Yearly"), /*#__PURE__*/React.createElement(Badge, {
    tone: "success"
  }, "Save 20%"))), /*#__PURE__*/React.createElement("section", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "20px 40px 60px",
      display: "grid",
      gridTemplateColumns: "repeat(3, 1fr)",
      gap: 20,
      alignItems: "stretch"
    }
  }, PLANS.map(p => /*#__PURE__*/React.createElement("div", {
    key: p.name,
    style: {
      display: "flex",
      flexDirection: "column",
      background: p.featured ? "var(--surface-primary)" : "var(--surface-card)",
      border: p.featured ? "1px solid var(--border-strong)" : "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 24
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 24,
      lineHeight: 1,
      letterSpacing: "-0.48px"
    }
  }, p.name), p.featured && /*#__PURE__*/React.createElement(Badge, {
    tone: "accent"
  }, "Most popular")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 24,
      display: "flex",
      alignItems: "flex-end",
      gap: 6
    }
  }, p.price ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 54,
      lineHeight: 1,
      letterSpacing: "-1.6px"
    }
  }, "$", p.price[yearly ? 1 : 0]), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)",
      paddingBottom: 6
    }
  }, "/ seat / mo")) : /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 54,
      lineHeight: 1,
      letterSpacing: "-1.6px"
    }
  }, "Custom")), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "16px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1.5,
      color: "var(--text-secondary)"
    }
  }, p.blurb), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 12,
      margin: "24px 0",
      paddingTop: 24,
      borderTop: "1px solid var(--border-default)"
    }
  }, p.features.map(f => /*#__PURE__*/React.createElement("div", {
    key: f,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 16,
    color: p.featured ? "var(--color-fin)" : "var(--text-primary)"
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, f)))), /*#__PURE__*/React.createElement(Button, {
    variant: p.variant,
    fullWidth: true,
    style: {
      marginTop: "auto"
    }
  }, p.cta)))), /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--surface-primary)",
      borderTop: "1px solid var(--border-default)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "60px 40px"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "Compare plans"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 24
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1.6fr 1fr 1fr 1fr",
      padding: "0 0 12px",
      borderBottom: "1px solid var(--border-strong)"
    }
  }, ["", "Essential", "Growth", "Enterprise"].map((h, i) => /*#__PURE__*/React.createElement(Eyebrow, {
    key: i,
    color: "var(--text-primary)"
  }, h))), ROWS.map(r => /*#__PURE__*/React.createElement("div", {
    key: r[0],
    style: {
      display: "grid",
      gridTemplateColumns: "1.6fr 1fr 1fr 1fr",
      padding: "16px 0",
      borderBottom: "1px solid var(--border-default)",
      alignItems: "center"
    }
  }, r.map((c, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      color: i === 0 ? "var(--text-primary)" : "var(--text-secondary)"
    }
  }, c))))))), /*#__PURE__*/React.createElement("section", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "80px 40px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "0.8fr 1.2fr",
      gap: 60
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: 40,
      lineHeight: 1,
      letterSpacing: "-1.2px",
      fontWeight: 400
    }
  }, "Questions we get every week"), /*#__PURE__*/React.createElement("div", null, [["What counts as a resolution?", "A conversation Fin closes without a human reply. If a teammate steps in, you're not charged."], ["Can we start with the inbox only?", "Yes. Essential has no Fin usage, and you can switch it on later without migrating anything."], ["Do you charge for light agents?", "No. Viewers and collaborators are free on every plan."]].map(([q, a]) => /*#__PURE__*/React.createElement("div", {
    key: q,
    style: {
      padding: "20px 0",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 24,
      lineHeight: 1,
      letterSpacing: "-0.48px"
    }
  }, q), /*#__PURE__*/React.createElement(Icon, {
    name: "plus",
    size: 18,
    color: "var(--text-muted)"
  })), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "14px 0 0",
      fontFamily: "var(--font-serif)",
      fontSize: 16,
      fontWeight: 300,
      lineHeight: 1.4,
      letterSpacing: "-0.16px",
      color: "var(--text-secondary)",
      maxWidth: 520
    }
  }, a)))))), /*#__PURE__*/React.createElement(CtaBand, null));
}
Object.assign(window, {
  PricingScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/PricingScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/ProductScreen.jsx
try { (() => {
// Product page for the AI agent: split hero, capability list, source table.
const CAPABILITIES = [["01", "Reads your content", "Point Fin at your help center, PDFs and past tickets. It cites what it used in every answer."], ["02", "Takes real actions", "Issue refunds, change a plan, resend a receipt — through the same APIs your team uses."], ["03", "Knows when to stop", "Low confidence, angry customer, VIP account: Fin hands over with a full summary attached."], ["04", "Improves weekly", "Every unresolved conversation becomes a content gap you can fix in one click."]];
function ProductScreen({
  onRoute
}) {
  const [tab, setTab] = React.useState("answers");
  return /*#__PURE__*/React.createElement("main", null, /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--surface-primary)",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "80px 40px",
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 60,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 10,
      height: 10,
      borderRadius: 999,
      background: "var(--color-fin)"
    }
  }), /*#__PURE__*/React.createElement(Eyebrow, {
    color: "var(--color-fin)"
  }, "Fin \xB7 AI agent")), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "24px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 80,
      lineHeight: 1,
      letterSpacing: "-2.4px",
      fontWeight: 400
    }
  }, "The agent that resolves, not deflects."), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "24px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 20,
      lineHeight: 0.95,
      letterSpacing: "-0.2px",
      color: "var(--text-secondary)",
      maxWidth: 480
    }
  }, "Answers grounded in your own content, with actions your customers can feel."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 12,
      marginTop: 32
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "accent",
    size: "lg"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles",
    size: 16,
    color: "currentColor"
  }), " Try Fin free"), /*#__PURE__*/React.createElement(Button, {
    variant: "outlined",
    size: "lg",
    onClick: () => onRoute("pricing")
  }, "See pricing"))), /*#__PURE__*/React.createElement("div", {
    style: {
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      background: "var(--surface-card)",
      padding: 20
    }
  }, /*#__PURE__*/React.createElement(Tabs, {
    items: [{
      value: "answers",
      label: "Answers"
    }, {
      value: "actions",
      label: "Actions"
    }, {
      value: "handover",
      label: "Handover"
    }],
    value: tab,
    onChange: setTab
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 20,
      display: "flex",
      flexDirection: "column",
      gap: 12,
      minHeight: 236
    }
  }, tab === "answers" && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 16,
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      lineHeight: 1.4
    }
  }, "Do you support SSO on the Growth plan?"), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 16
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      lineHeight: 1.4
    }
  }, "SAML SSO is included on Growth and above. You can enable it in Settings \u2192 Security; the setup takes about ten minutes."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      marginTop: 14,
      paddingTop: 14,
      borderTop: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "book-open",
    size: 14,
    color: "var(--color-fin)"
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      letterSpacing: "0.6px",
      textTransform: "uppercase",
      color: "var(--text-muted)"
    }
  }, "Source: security/sso-setup")))), tab === "actions" && /*#__PURE__*/React.createElement(React.Fragment, null, [["credit-card", "Refund issued", "$49.00 · card ending 4242"], ["user-cog", "Plan changed", "Starter → Growth, prorated"], ["mail", "Receipt resent", "dana@northwind.com"]].map(([ic, t, s]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 14,
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 16
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: ic,
    size: 20,
    color: "var(--text-primary)"
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 16
    }
  }, t), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      fontWeight: 300,
      color: "var(--text-muted)"
    }
  }, s)), /*#__PURE__*/React.createElement(Badge, {
    tone: "success",
    style: {
      marginLeft: "auto"
    }
  }, "Done")))), tab === "handover" && /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--surface-primary)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-card)",
      padding: 16
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "Handover summary"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "14px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 14,
      lineHeight: 1.4
    }
  }, "Customer was charged twice and is on a VIP account. Fin verified both charges, refunded one, and escalated because the customer asked for a call. Sentiment: frustrated."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 16
    }
  }, /*#__PURE__*/React.createElement(Tag, {
    selected: true
  }, "VIP"), /*#__PURE__*/React.createElement(Tag, null, "Billing"), /*#__PURE__*/React.createElement(Tag, null, "Callback requested"))))))), /*#__PURE__*/React.createElement("section", {
    style: {
      maxWidth: 1200,
      margin: "0 auto",
      padding: "80px 40px"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "How it works"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(2, 1fr)",
      gap: 0,
      marginTop: 32,
      borderTop: "1px solid var(--border-default)"
    }
  }, CAPABILITIES.map(([n, t, b]) => /*#__PURE__*/React.createElement("div", {
    key: n,
    style: {
      display: "grid",
      gridTemplateColumns: "56px 1fr",
      gap: 20,
      padding: "32px 40px 32px 0",
      borderBottom: "1px solid var(--border-default)"
    }
  }, /*#__PURE__*/React.createElement(Eyebrow, {
    style: {
      paddingTop: 6
    }
  }, n), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: "var(--font-sans)",
      fontSize: 32,
      lineHeight: 1,
      letterSpacing: "-0.96px",
      fontWeight: 400
    }
  }, t), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "16px 0 0",
      fontFamily: "var(--font-sans)",
      fontSize: 16,
      lineHeight: 1.5,
      color: "var(--text-secondary)",
      maxWidth: 420,
      textWrap: "pretty"
    }
  }, b)))))), /*#__PURE__*/React.createElement(CtaBand, null));
}
Object.assign(window, {
  ProductScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/ProductScreen.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.Tag = __ds_scope.Tag;

__ds_ns.Dialog = __ds_scope.Dialog;

__ds_ns.Toast = __ds_scope.Toast;

__ds_ns.Tooltip = __ds_scope.Tooltip;

__ds_ns.Checkbox = __ds_scope.Checkbox;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Radio = __ds_scope.Radio;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.Switch = __ds_scope.Switch;

__ds_ns.Tabs = __ds_scope.Tabs;

})();
