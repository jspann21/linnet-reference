import { Screen, VideoSurface, StatusBar, ProgressBar, Text } from "@linnet/ui";
export default function Scene() { return (<Screen><VideoSurface x={0} y={0} w={220} h={176} text="" /><StatusBar w={220} h={20} text="Video" bg="theme.panel" /><ProgressBar x={6} y={149} w={208} h={8} count={1000} /><Text x={5} y={160} w={210} h={16} text="Play: Pause  Left/Right: Seek" /></Screen>); }
