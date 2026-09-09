import { Screen, StatusBar, VirtualList } from "@linnet/ui";
export default function Scene() { return (
<Screen><StatusBar w={220} h={20} text="Videos" bg="theme.panel" />
<VirtualList x={4} y={24} w={208} h={148} count={0} text="Videos" focus={true} />
</Screen>
); }
