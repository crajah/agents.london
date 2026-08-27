import React from 'react';

/**
 * agents.london logo — network constellation mark + wordmark.
 * The mark represents interconnected agent nodes forming a unified system.
 */
export default function Logo({ size = 32, showText = true, variant = 'default' }) {
  const markSize = size;
  const textColor = variant === 'light' ? '#18181b' : variant === 'auto' ? 'currentColor' : '#fafafa';
  const accentColor = '#537ebf';
  const secondaryColor = '#7ac943';

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.25, lineHeight: 1 }}>
      {/* Mark — constellation of connected nodes */}
      <svg width={markSize} height={markSize} viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Outer ring */}
        <circle cx="24" cy="24" r="22" stroke={accentColor} strokeWidth="1.5" strokeOpacity="0.25" fill="none" />

        {/* Connection lines */}
        <line x1="24" y1="10" x2="12" y2="28" stroke={secondaryColor} strokeWidth="1.2" strokeOpacity="0.5" />
        <line x1="24" y1="10" x2="36" y2="28" stroke={secondaryColor} strokeWidth="1.2" strokeOpacity="0.5" />
        <line x1="12" y1="28" x2="36" y2="28" stroke={secondaryColor} strokeWidth="1.2" strokeOpacity="0.5" />
        <line x1="24" y1="10" x2="24" y2="38" stroke={accentColor} strokeWidth="1.2" strokeOpacity="0.4" />
        <line x1="12" y1="28" x2="24" y2="38" stroke={accentColor} strokeWidth="1.2" strokeOpacity="0.4" />
        <line x1="36" y1="28" x2="24" y2="38" stroke={accentColor} strokeWidth="1.2" strokeOpacity="0.4" />
        <line x1="8" y1="18" x2="24" y2="10" stroke={secondaryColor} strokeWidth="1" strokeOpacity="0.3" />
        <line x1="40" y1="18" x2="24" y2="10" stroke={secondaryColor} strokeWidth="1" strokeOpacity="0.3" />
        <line x1="8" y1="18" x2="12" y2="28" stroke={secondaryColor} strokeWidth="1" strokeOpacity="0.3" />
        <line x1="40" y1="18" x2="36" y2="28" stroke={secondaryColor} strokeWidth="1" strokeOpacity="0.3" />

        {/* Primary nodes */}
        <circle cx="24" cy="10" r="3.5" fill={accentColor} />
        <circle cx="12" cy="28" r="3" fill={accentColor} />
        <circle cx="36" cy="28" r="3" fill={accentColor} />
        <circle cx="24" cy="38" r="2.5" fill={secondaryColor} />

        {/* Secondary nodes */}
        <circle cx="8" cy="18" r="2" fill={secondaryColor} fillOpacity="0.7" />
        <circle cx="40" cy="18" r="2" fill={secondaryColor} fillOpacity="0.7" />

        {/* Center glow */}
        <circle cx="24" cy="24" r="2" fill={accentColor} fillOpacity="0.6" />
        <circle cx="24" cy="24" r="5" fill={accentColor} fillOpacity="0.08" />
      </svg>

      {/* Wordmark */}
      {showText && (
        <span style={{
          fontFamily: '"Archivo", system-ui, sans-serif',
          fontWeight: 800,
          fontSize: size * 0.55,
          letterSpacing: '-0.03em',
          color: textColor,
        }}>
          agents
          <span style={{ color: accentColor }}>.london</span>
        </span>
      )}
    </span>
  );
}
