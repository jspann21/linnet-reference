import { Screen, StatusBar, Text } from "@linnet/ui";
export default function Scene() { return (
<Screen><StatusBar w={220} h={20} text="Videos" bg="theme.panel" />
<Text x={8} y={42} w={204} h={24} text="Prepared video" />
<Text x={8} y={80} w={204} h={24} text="Select: play or resume" />
<Text x={8} y={116} w={204} h={24} text="Menu: home" /></Screen>
); }
