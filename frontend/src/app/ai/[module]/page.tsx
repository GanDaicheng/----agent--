import type { Metadata } from "next";

import { ModuleRoutePage } from "@/components/platform/ModuleRoutePage";
import { getModule, getSection } from "@/features/platform/platform-config";

const SECTION_ID = "ai";

export function generateStaticParams() {
  return (
    getSection(SECTION_ID)?.modules.map((module) => ({
      module: module.slug,
    })) ?? []
  );
}

export async function generateMetadata(
  props: PageProps<"/ai/[module]">,
): Promise<Metadata> {
  const { module } = await props.params;
  const found = getModule(SECTION_ID, module);

  return found
    ? { title: found.name, description: found.summary }
    : { title: "未找到模块" };
}

export default async function Page(props: PageProps<"/ai/[module]">) {
  const { module } = await props.params;

  return <ModuleRoutePage sectionId={SECTION_ID} slug={module} />;
}
