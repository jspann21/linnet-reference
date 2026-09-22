import { Screen, VideoSurface, StatusBar, ProgressBar, Text } from "@linnet/ui";
export default function Scene() { return (<Screen><VideoSurface x={0} y={0} w={320} h={240} text="" /><StatusBar w={320} h={28} text="Video" bg="theme.panel" /><ProgressBar x={8} y={203} w={302} h={10} count={1000} /><Text x={7} y={218} w={305} h={21} text="Play: Pause  Left/Right: Seek" /></Screen>); }
