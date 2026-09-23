import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes } from "react";

import styles from "./Button.module.css";

/** 主按钮用于「这一页要做的那件事」，一屏之内只该有一个；其余一律次按钮。 */
export type ButtonVariant = "primary" | "secondary";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

/**
 * 按钮。
 *
 * 默认 type="button"：原生 button 在表单里默认是 submit，
 * 这个项目里所有按钮都靠 onClick 干活，不写 type 迟早会有一个按钮意外提交表单。
 */
export function Button({
  variant = "secondary",
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={[styles.button, styles[variant], className]
        .filter(Boolean)
        .join(" ")}
    />
  );
}

type LinkButtonProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  variant?: ButtonVariant;
};

/**
 * 长得像按钮的链接。
 *
 * 与 Button 分开是必要的：一个是「点一下做一件事」，一个是「跳到一个页面」。
 * 用 button 加 router.push 模拟跳转会丢掉中键新开、右键复制链接这些浏览器原生行为。
 * 样式复用同一个 CSS Module，所以两者看起来完全一样。
 */
export function LinkButton({
  href,
  variant = "secondary",
  className,
  children,
  ...rest
}: LinkButtonProps) {
  return (
    <Link
      {...rest}
      href={href}
      className={[styles.button, styles[variant], className]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Link>
  );
}
