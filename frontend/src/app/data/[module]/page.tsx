import type { Metadata } from "next";

import { ModuleRoutePage } from "@/components/platform/ModuleRoutePage";
import { getModule, getSection } from "@/features/platform/platform-config";

const SECTION_ID = "data";

/**
 * 已经拥有独立静态路由的模块（app/data/<slug>/page.tsx）。
 *
 * 必须在这里排除：否则同一个路径会被动态路由和静态路由各预渲染一遍，
 * 构建产物里出现两份 /data/sources。静态路由优先，所以访问结果是对的，
 * 但那份额外的产物纯属浪费且容易让人误解。
 * 与 app/applications/[module]/page.tsx 的处理方式一致。
 */
const STATIC_ROUTE_SLUGS = new Set(["sources"]);

export function generateStaticParams() {
  return (
    getSection(SECTION_ID)?.modules
      .filter((module) => !STATIC_ROUTE_SLUGS.has(module.slug))
      .map((module) => ({
        module: module.slug,
      })) ?? []
  );
}

export async function generateMetadata(
  props: PageProps<"/data/[module]">,
): Promise<Metadata> {
  const { module } = await props.params;
  const found = getModule(SECTION_ID, module);

  return found
    ? { title: found.name, description: found.summary }
    : { title: "未找到模块" };
}

export default async function Page(props: PageProps<"/data/[module]">) {
  const { module } = await props.params;

  return <ModuleRoutePage sectionId={SECTION_ID} slug={module} />;
}
