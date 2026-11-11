/**
 * SplitText for Hugo
 * A dependency-free, vanilla-JS adaptation of the React Bits SplitText component.
 *
 * Usage: add data-split-text to any element, then optionally:
 *   data-split-type="chars|words"
 *   data-split-effect="rise|fade|blur|flip|pop|skew|wave"
 *   data-split-trigger="view|load|hover|click"
 *   data-split-delay="50" data-split-duration="1.25" data-split-ease="..."
 *   data-split-stagger-from="start|center|end|edges|random"
 *   data-split-mask="true"
 *   data-split-loop="true" data-split-loop-delay="1.5"
 *   data-split-hover="none|lift|wave"
 *   data-split-accent="var(--accent-color)"
 *   data-split-threshold="0.1" data-split-root-margin="0px 0px -10% 0px"
 *
 * Fires a "splittext:complete" CustomEvent once after the first reveal.
 */

(() => {
  'use strict';

  const BASE_EASING = 'cubic-bezier(0.22, 1, 0.36, 1)';
  const EXIT_EASING = 'cubic-bezier(0.5, 0, 0.75, 0)';
  const STIFFNESS = 180;
  const DAMPING = 19;
  const KICK = 0.024;

  const EFFECTS = {
    rise: {
      from: { opacity: 0, transform: 'translateY(0.55em)' },
      to: { opacity: 1, transform: 'translateY(0)' },
      ease: 'cubic-bezier(0.22, 1, 0.36, 1)'
    },
    fade: {
      from: { opacity: 0 },
      to: { opacity: 1 },
      ease: 'ease-in-out'
    },
    blur: {
      from: { opacity: 0, filter: 'blur(8px)' },
      to: { opacity: 1, filter: 'blur(0px)' },
      ease: 'cubic-bezier(0.22, 1, 0.36, 1)'
    },
    flip: {
      from: { opacity: 0, transform: 'perspective(600px) rotateX(-90deg)' },
      to: { opacity: 1, transform: 'perspective(600px) rotateX(0deg)' },
      ease: 'cubic-bezier(0.22, 1, 0.36, 1)'
    },
    pop: {
      from: { opacity: 0, transform: 'scale(0.65)' },
      to: { opacity: 1, transform: 'scale(1)' },
      ease: 'cubic-bezier(0.34, 1.56, 0.64, 1)'
    },
    skew: {
      from: { opacity: 0, transform: 'translateX(-0.35em) skewX(-18deg)' },
      to: { opacity: 1, transform: 'translateX(0) skewX(0)' },
      ease: 'cubic-bezier(0.16, 1, 0.3, 1)'
    },
    wave: {
      from: { opacity: 0, transform: 'translateY(0.45em)' },
      to: { opacity: 1, transform: 'translateY(0)' },
      ease: 'cubic-bezier(0.25, 0.9, 0.3, 1)'
    }
  };

  const prefersReducedMotion = () =>
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const makePiece = (text, type, masked) => {
    const inner = document.createElement('span');
    inner.className = 'split-piece ' + (type === 'words' ? 'split-word' : 'split-char');
    inner.textContent = text;
    inner.setAttribute('aria-hidden', 'true');

    if (!masked) {
      return { unit: inner, inner, mover: inner };
    }

    const mask = document.createElement('span');
    mask.className = 'split-mask';
    mask.setAttribute('aria-hidden', 'true');
    mask.appendChild(inner);
    return { unit: mask, inner, mover: mask };
  };

  const splitText = (root, type, masked) => {
    const pieces = [];

    const splitTextNode = (node) => {
      const text = node.textContent;
      if (!text) return;

      const fragment = document.createDocumentFragment();
      const tokens = type === 'words' ? text.match(/\S+|\s+/g) || [] : Array.from(text);

      tokens.forEach((token) => {
        if (/^\s+$/.test(token)) {
          fragment.appendChild(document.createTextNode(token));
          return;
        }

        const piece = makePiece(token, type, masked);
        fragment.appendChild(piece.unit);
        pieces.push(piece);
      });

      node.parentNode.replaceChild(fragment, node);
    };

    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        splitTextNode(node);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (['BR', 'SCRIPT', 'STYLE'].includes(node.tagName)) return;
      Array.from(node.childNodes).forEach(walk);
    };

    Array.from(root.childNodes).forEach(walk);
    return pieces;
  };

  const orderedIndexes = (length, from) => {
    const indexes = Array.from({ length }, (_, index) => index);
    const center = (length - 1) / 2;

    switch (from) {
      case 'end':
        return indexes.reverse();
      case 'center':
        return indexes.sort((a, b) => Math.abs(a - center) - Math.abs(b - center));
      case 'edges':
        return indexes.sort((a, b) => Math.abs(b - center) - Math.abs(a - center));
      case 'random':
        for (let i = indexes.length - 1; i > 0; i -= 1) {
          const j = Math.floor(Math.random() * (i + 1));
          [indexes[i], indexes[j]] = [indexes[j], indexes[i]];
        }
        return indexes;
      default:
        return indexes;
    }
  };

  const init = (element) => {
    if (element.dataset.splitReady === 'true') return;
    if (prefersReducedMotion()) return;

    const effectName = element.dataset.splitEffect || 'rise';
    const effect = EFFECTS[effectName] || EFFECTS.rise;
    const splitType = element.dataset.splitType || 'chars';
    const type = splitType.includes('chars') ? 'chars' : 'words';
    const masked = element.dataset.splitMask === 'true';
    const delay = Number(element.dataset.splitDelay || 50);
    const duration = Number(element.dataset.splitDuration || 1.25) * 1000;
    const exitDuration = Math.max(350, duration * 0.55);
    const loop = element.dataset.splitLoop === 'true';
    const loopDelay = Math.max(0, Number(element.dataset.splitLoopDelay || 1.5) * 1000);
    const hoverEffect = element.dataset.splitHover || 'none';
    const trigger = element.dataset.splitTrigger || 'view';
    const threshold = Number(element.dataset.splitThreshold || 0.1);
    const rootMargin = element.dataset.splitRootMargin || '0px 0px -10% 0px';
    const ease = element.dataset.splitEase || effect.ease || BASE_EASING;

    const label = element.textContent.replace(/\s+/g, ' ').trim();
    const pieces = splitText(element, type, masked);
    if (!pieces.length) return;

    pieces.forEach((piece) => {
      piece.color = getComputedStyle(piece.inner).color;
    });

    element.dataset.splitReady = 'true';
    element.setAttribute('aria-label', label);

    const order = orderedIndexes(pieces.length, element.dataset.splitStaggerFrom || 'start');
    const orderPosition = new Map(order.map((index, position) => [index, position]));
    const computedColor = getComputedStyle(element).color;

    const resolveColor = (value) => {
      if (!value) return '';
      const match = /^var\((--[^)]+)\)$/.exec(value.trim());
      if (!match) return value;
      return getComputedStyle(element).getPropertyValue(match[1]).trim() || value;
    };

    const accentColor = resolveColor(element.dataset.splitAccent || '');

    const setStyles = (styleMap) => {
      pieces.forEach(({ inner }) => {
        inner.style.opacity = styleMap.opacity !== undefined ? String(styleMap.opacity) : '';
        inner.style.transform = styleMap.transform || 'none';
        inner.style.filter = styleMap.filter || 'none';
      });
    };

    const runAnimation = (from, to, durationMs, easing) => {
      const animations = pieces.map((piece, index) => {
        const orderIndex = orderPosition.get(index) || 0;
        const animation = piece.inner.animate([from, to], {
          duration: durationMs,
          delay: orderIndex * delay,
          easing,
          fill: 'both'
        });
        return animation.finished.catch(() => undefined);
      });

      return Promise.all(animations);
    };

    const runAccent = () => {
      if (!accentColor) return;
      pieces.forEach((piece, index) => {
        const orderIndex = orderPosition.get(index) || 0;
        const targetColor = piece.color || computedColor;
        const animation = piece.inner.animate(
          [{ color: accentColor }, { color: targetColor }],
          {
            duration: duration * 0.7,
            delay: duration * 0.3 + orderIndex * delay,
            easing: 'ease-in-out',
            fill: 'both'
          }
        );
        animation.addEventListener(
          'finish',
          () => {
            piece.inner.style.color = targetColor;
            animation.cancel();
          },
          { once: true }
        );
      });
    };

    let revealed = false;
    let busy = false;
    let announced = false;
    let loopTimer = 0;

    const announce = () => {
      if (announced) return;
      announced = true;
      element.dispatchEvent(
        new CustomEvent('splittext:complete', {
          bubbles: true,
          detail: { text: label }
        })
      );
    };

    const queueLoop = () => {
      if (!loop) return;
      clearTimeout(loopTimer);
      loopTimer = window.setTimeout(async () => {
        if (busy) {
          queueLoop();
          return;
        }
        if (!revealed) return;
        await conceal();
        await reveal();
      }, loopDelay);
    };

    const reveal = async () => {
      if (busy || revealed) return;
      busy = true;
      setStyles(effect.from);
      const animation = runAnimation(effect.from, effect.to, duration, ease);
      runAccent();
      await animation;
      setStyles(effect.to);
      revealed = true;
      busy = false;
      announce();
      queueLoop();
    };

    const conceal = async () => {
      if (busy || !revealed) return;
      busy = true;
      await runAnimation(effect.to, effect.from, exitDuration, EXIT_EASING);
      setStyles(effect.from);
      revealed = false;
      busy = false;
    };

    const cycle = async () => {
      if (busy || !revealed) return;
      await conceal();
      await reveal();
    };

    // Hover physics: lift / wave
    const em = parseFloat(getComputedStyle(element).fontSize) || 16;
    const lift = em * 0.2;
    const springs = pieces.map(() => ({ y: 0, v: 0 }));
    const kicks = [];
    const pointer = { x: 0, y: 0, inside: false };
    let centers = null;
    let raf = 0;
    let last = 0;

    const measure = () => {
      const box = element.getBoundingClientRect();
      centers = pieces.map((piece, index) => {
        const rect = piece.mover.getBoundingClientRect();
        return {
          x: rect.left + rect.width / 2 - box.left,
          y: rect.top + rect.height / 2 - box.top - (springs[index].y || 0)
        };
      });
    };

    const tick = (now) => {
      raf = 0;
      const dt = Math.min(0.032, Math.max(0.001, (now - last) / 1000));
      last = now;
      const lifting = hoverEffect === 'lift' && pointer.inside && revealed;
      const radius = em * 1.15;
      let moving = false;

      for (let k = kicks.length - 1; k >= 0; k -= 1) {
        if (now < kicks[k].at) continue;
        const spring = springs[kicks[k].index];
        if (spring) spring.v -= kicks[k].velocity;
        kicks.splice(k, 1);
      }

      pieces.forEach((piece, index) => {
        const spring = springs[index];
        let target = 0;

        if (lifting && centers) {
          const dx = (centers[index].x - pointer.x) / radius;
          const dy = (centers[index].y - pointer.y) / (radius * 1.4);
          target = -lift * Math.exp(-(dx * dx + dy * dy) * 0.5);
        }

        spring.v += (STIFFNESS * (target - spring.y) - DAMPING * spring.v) * dt;
        spring.y += spring.v * dt;

        if (Math.abs(target - spring.y) < 0.02 && Math.abs(spring.v) < 0.05) {
          spring.y = target;
          spring.v = 0;
        } else {
          moving = true;
        }

        piece.mover.style.translate =
          Math.abs(spring.y) > 0.01 ? '0 ' + spring.y.toFixed(2) + 'px' : '';
      });

      if (moving || kicks.length) raf = requestAnimationFrame(tick);
    };

    const wake = () => {
      if (raf) return;
      last = performance.now();
      raf = requestAnimationFrame(tick);
    };

    const locate = (event) => {
      const box = element.getBoundingClientRect();
      pointer.x = event.clientX - box.left;
      pointer.y = event.clientY - box.top;
    };

    const onPointerEnter = (event) => {
      locate(event);
      pointer.inside = true;
      if (!revealed) return;
      if (trigger === 'hover') cycle();
      if (hoverEffect === 'none') return;
      measure();
      if (hoverEffect === 'wave') {
        const now = performance.now();
        const speed = em * 9;
        const velocity = (em * 0.16) / KICK;
        centers.forEach((center, index) => {
          kicks.push({
            index,
            velocity,
            at: now + (Math.abs(center.x - pointer.x) / speed) * 1000
          });
        });
      }
      wake();
    };

    const onPointerMove = (event) => {
      locate(event);
      pointer.inside = true;
      if (!revealed || hoverEffect !== 'lift') return;
      if (!centers) measure();
      wake();
    };

    const onPointerLeave = () => {
      pointer.inside = false;
      wake();
    };

    const onClick = () => {
      if (trigger !== 'click') return;
      if (!revealed) reveal();
      else cycle();
    };

    if (hoverEffect !== 'none') {
      element.addEventListener('pointerenter', onPointerEnter);
      element.addEventListener('pointermove', onPointerMove);
      element.addEventListener('pointerleave', onPointerLeave);
    }

    if (trigger === 'click') {
      element.addEventListener('click', onClick);
    }

    setStyles(effect.from);

    if (trigger === 'load') {
      reveal();
    } else if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            observer.disconnect();
            reveal();
          }
        },
        { threshold, rootMargin }
      );
      observer.observe(element);
    } else {
      reveal();
    }
  };

  const start = () => {
    document.querySelectorAll('[data-split-text]').forEach(init);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
