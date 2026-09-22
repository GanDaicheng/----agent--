import { notFound } from "next/navigation";

import {
  getModule,
  getSection,
  type SectionId,
} from "@/features/platform/platform-config";

import { ModulePage } from "./ModulePage";

type Props = {
  sectionId: SectionId;
  /** 路由动态段 app/<section>/[module] 的值。 */
  slug: string;
};

/**
 * 把动态路由的 [module] 解析成配置里的模块，然后交给通用模块页模板渲染。
 *
 * 四个路由段页面共用这一处查找逻辑，配置里没有的模块直接返回 404，
 * 不会渲染出一个空白但仍可访问的页面。
 */
export function ModuleRoutePage({ sectionId, slug }: Props) {
  const section = getSection(sectionId);
  const moduleConfig = section ? getModule(sectionId, slug) : undefined;

  if (!section || !moduleConfig) {
    notFound();
  }

  return <ModulePage section={section} module={moduleConfig} />;
}
