/**
 * MeetTrace Google Meet Lifecycle & Metadata Detector.
 *
 * Runs as a content script on https://meet.google.com/* to detect:
 * - MEETING_DETECTED: user entered a meeting URL / pre-call lobby
 * - MEETING_STARTED: user joined the active meeting
 * - MEETING_ENDED: user left or disconnected from the meeting
 *
 * Tolerate SPA navigation, DOM modifications, and multi-language UI.
 * Does NOT access audio, microphone, video, or participant identities.
 */

(function () {
  "use strict";

  const ROOM_CODE_REGEX = /\/([a-z]{3}-[a-z]{4}-[a-z]{3})/i;

  const STATES = {
    IDLE: "IDLE",
    DETECTED: "DETECTED",
    STARTED: "STARTED",
    ENDED: "ENDED",
  };

  class MeetDetector {
    constructor() {
      this.currentState = STATES.IDLE;
      this.currentMeetingCode = null;
      this.currentTitle = "";
      this.debounceTimer = null;
      this.observer = null;
      this.intervalId = null;
    }

    /**
     * Extract meeting room code from URL pathname or query.
     */
    extractMeetingCode(pathname = window.location.pathname) {
      const match = pathname.match(ROOM_CODE_REGEX);
      return match ? match[1].toLowerCase() : null;
    }

    /**
     * Check if currently on a Google Meet room page (not landing/home).
     */
    isRoomPage() {
      return Boolean(this.extractMeetingCode());
    }

    /**
     * Extract a clean, human-readable meeting title.
     */
    extractTitle() {
      // 1. Try explicit meeting title element in call bottom bar
      const titleElem =
        document.querySelector("[data-meeting-title]") ||
        document.querySelector("div[jsname='Eydvaf']") ||
        document.querySelector("div[role='heading'][aria-level='1']");

      if (titleElem && titleElem.textContent) {
        const text = titleElem.textContent.trim();
        if (text && text.length < 150) {
          return text;
        }
      }

      // 2. Parse document.title (e.g. "Meet - abc-defg-hij" or "Meeting Name - Google Meet")
      const rawTitle = document.title || "";
      let clean = rawTitle
        .replace(/^Meet\s*[-–—]\s*/i, "")
        .replace(/\s*[-–—]\s*Google Meet$/i, "")
        .replace(/\s*[-–—]\s*Meet$/i, "")
        .trim();

      const code = this.extractMeetingCode();
      if (clean && clean !== code && clean !== "Google Meet" && clean.length < 150) {
        return clean;
      }

      // Fallback to room code or generic
      return code ? `Meet (${code})` : "Google Meet";
    }

    /**
     * Multi-signal heuristic to check if call is active ("in-call").
     */
    isInCall() {
      if (!this.isRoomPage()) {
        return false;
      }

      // Signal 1: Leave / End call button present
      const leaveSelectors = [
        "button[data-tooltip*='leave' i]",
        "button[aria-label*='leave' i]",
        "button[aria-label*='звонок' i]",
        "button[aria-label*='выйти' i]",
        "button[aria-label*='покинуть' i]",
        "button[aria-label*='end call' i]",
        "button[jsname='CQylAd']",
        "[data-call-end]",
      ];
      for (const selector of leaveSelectors) {
        if (document.querySelector(selector)) {
          return true;
        }
      }

      // Signal 2: Call controls bar with mute/camera buttons
      const controlSelectors = [
        "div[role='region'][aria-label*='call' i]",
        "div[role='region'][aria-label*='встреч' i]",
        "div[role='region'][aria-label*='управлен' i]",
        "div[jscontroller='kAPstf']",
        "button[data-is-muted]",
      ];
      for (const selector of controlSelectors) {
        if (document.querySelector(selector)) {
          return true;
        }
      }

      return false;
    }

    /**
     * Multi-signal heuristic to check if call has ended / user left.
     */
    isCallEnded() {
      // If we previously started a call and are no longer in-call on room page
      const endedIndicators = [
        "button[aria-label*='rejoin' i]",
        "button[aria-label*='присоединиться повторно' i]",
        "a[href*='landing']",
        "[data-call-ended='true']",
      ];
      for (const selector of endedIndicators) {
        if (document.querySelector(selector)) {
          return true;
        }
      }

      // Text search in document for post-call strings
      const bodyText = document.body ? document.body.innerText || "" : "";
      if (
        bodyText.includes("You left the meeting") ||
        bodyText.includes("You've left the meeting") ||
        bodyText.includes("Вы вышли из встречи") ||
        bodyText.includes("Ви вийшли з зустрічі") ||
        bodyText.includes("Return to home screen")
      ) {
        return true;
      }

      return false;
    }

    /**
     * Determine current lifecycle state based on DOM and navigation signals.
     */
    evaluateState() {
      const code = this.extractMeetingCode();

      if (!code) {
        // Not a room URL
        if (this.currentState === STATES.STARTED || this.currentState === STATES.DETECTED) {
          return STATES.ENDED;
        }
        return STATES.IDLE;
      }

      // Room URL is active
      if (this.isInCall()) {
        return STATES.STARTED;
      }

      if (this.isCallEnded()) {
        return STATES.ENDED;
      }

      // In room URL but not yet joined call (e.g. green room / pre-join lobby)
      return STATES.DETECTED;
    }

    /**
     * Check state and dispatch lifecycle event if transition occurs.
     */
    checkLifecycle() {
      const newState = this.evaluateState();
      const code = this.extractMeetingCode();

      if (newState === this.currentState && code === this.currentMeetingCode) {
        return;
      }

      const previousState = this.currentState;
      this.currentState = newState;
      this.currentMeetingCode = code;
      this.currentTitle = this.extractTitle();

      let eventType = null;
      if (newState === STATES.DETECTED && previousState !== STATES.DETECTED) {
        eventType = "MEETING_DETECTED";
      } else if (newState === STATES.STARTED && previousState !== STATES.STARTED) {
        eventType = "MEETING_STARTED";
      } else if (newState === STATES.ENDED && previousState === STATES.STARTED) {
        eventType = "MEETING_ENDED";
      }

      if (eventType) {
        this.emitLifecycleEvent(eventType);
      }
    }

    /**
     * Emit authenticated message to Chrome background service worker.
     */
    emitLifecycleEvent(eventType) {
      const payload = {
        event: eventType,
        meeting: {
          url: window.location.href,
          title: this.currentTitle || this.extractTitle(),
          meeting_code: this.currentMeetingCode || "",
          detected_at: new Date().toISOString(),
          browser: "chrome",
        },
      };

      try {
        if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
          chrome.runtime.sendMessage(payload, (response) => {
            if (chrome.runtime.lastError) {
              // Service worker might be sleeping or desktop app offline
            }
          });
        }
      } catch (err) {
        // Silently swallow extension communication errors
      }
    }

    /**
     * Start observers and listeners.
     */
    start() {
      // 1. Initial check
      this.checkLifecycle();

      // 2. Observe DOM mutations (debounced)
      this.observer = new MutationObserver(() => {
        if (this.debounceTimer) {
          clearTimeout(this.debounceTimer);
        }
        this.debounceTimer = setTimeout(() => {
          this.checkLifecycle();
        }, 400);
      });

      this.observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["data-meeting-title", "aria-label", "data-is-muted", "class"],
      });

      // 3. Fallback interval check
      this.intervalId = setInterval(() => {
        this.checkLifecycle();
      }, 2000);

      // 4. Listen for SPA popstate navigation
      window.addEventListener("popstate", () => {
        this.checkLifecycle();
      });

      // 5. Handle page unload
      window.addEventListener("beforeunload", () => {
        if (this.currentState === STATES.STARTED) {
          this.emitLifecycleEvent("MEETING_ENDED");
        }
      });
    }

    stop() {
      if (this.observer) {
        this.observer.disconnect();
        this.observer = null;
      }
      if (this.intervalId) {
        clearInterval(this.intervalId);
        this.intervalId = null;
      }
      if (this.debounceTimer) {
        clearTimeout(this.debounceTimer);
        this.debounceTimer = null;
      }
    }
  }

  // Self-start if running in browser window
  if (typeof window !== "undefined" && !window.__MEETTRACE_DETECTOR__) {
    const detector = new MeetDetector();
    window.__MEETTRACE_DETECTOR__ = detector;
    detector.start();
  }

  // Export for testing
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      ROOM_CODE_REGEX,
      STATES,
      MeetDetector,
    };
  }
})();
