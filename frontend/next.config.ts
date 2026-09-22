import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 让 next build 额外产出 .next/standalone：Next.js 会静态分析每个页面真正用到的
  // 文件，只把这些挑出来，产出一个自带最小 node_modules 的可独立部署目录。
  // 没有它的话，运行镜像就得把完整的开发依赖装进去，体积差好几倍。
  output: "standalone",
};

export default nextConfig;
