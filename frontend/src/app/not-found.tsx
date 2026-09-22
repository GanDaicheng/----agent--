import Link from "next/link";

import styles from "./not-found.module.css";

export default function NotFound() {
  return (
    <div className={styles.page}>
      <p className={styles.code}>404</p>
      <h1 className={styles.title}>页面不存在</h1>
      <p className={styles.desc}>
        该地址不属于平台已规划的任何模块。左侧导航列出了当前全部已规划的路由。
      </p>
      <Link href="/" className={styles.link}>
        返回平台总览
      </Link>
    </div>
  );
}
