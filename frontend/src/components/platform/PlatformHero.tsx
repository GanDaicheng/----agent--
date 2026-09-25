import { PLATFORM_BADGE } from "@/features/platform/platform-config";
import { OVERVIEW_HERO } from "@/features/platform/overview-config";

import styles from "./PlatformHero.module.css";

/**
 * 总览页页头。
 *
 * 三件事按重要性排：这是什么平台 → 它靠什么做到 → 数据口径的边界。
 * 能力标签是文案不是按钮——真正的入口在下面的业务卡片里，
 * 这里再放一遍可点的东西只会让人不知道该点哪个。
 */
export function PlatformHero() {
  return (
    <section className={styles.hero}>
      <p className={styles.badge}>{PLATFORM_BADGE}</p>

      <h1 className={styles.title}>{OVERVIEW_HERO.title}</h1>
      <p className={styles.subtitle}>{OVERVIEW_HERO.subtitle}</p>

      <ul className={styles.tags}>
        {OVERVIEW_HERO.tags.map((tag, index) => (
          <li key={tag} className={styles.tag} data-tone={index}>
            {tag}
          </li>
        ))}
      </ul>

      <p className={styles.note}>{OVERVIEW_HERO.note}</p>
    </section>
  );
}
