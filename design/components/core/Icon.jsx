import React from "react";

// Lucide (CDN) is the substituted icon set — see readme.md ICONOGRAPHY.
const CDN = "https://unpkg.com/lucide-static@0.544.0/icons/";

export function Icon({ name, size = 20, strokeWidth, color = "currentColor", style, ...rest }) {
  const url = `url("${CDN}${name}.svg")`;
  return (
    <span
      role="img"
      aria-label={name}
      style={{
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
        ...style,
      }}
      {...rest}
    />
  );
}
