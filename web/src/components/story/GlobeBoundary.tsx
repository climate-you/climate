"use client";

import { Component, type ReactNode } from "react";
import styles from "./story.module.css";

type Props = { children: ReactNode };
type State = { failed: boolean };

// The interactive globe needs WebGL. If it fails to initialize (unsupported
// browser, blocked context), fall back to a static note rather than letting the
// error take down the whole story page.
export default class GlobeBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className={styles.globeStage}>
          <span className={styles.globeBadge}>Interactive</span>
          <div
            className={styles.globeCanvasWrap}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "32px 26px",
              textAlign: "center",
            }}
          >
            <p className={styles.secNote} style={{ margin: 0 }}>
              The interactive globe needs a WebGL-capable browser. The maps
              above show the same data for each window.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
