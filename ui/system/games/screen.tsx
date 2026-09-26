import { Screen, StatusBar, Menu, Text } from "@linnet/ui";
export default function Scene() {
  return (<Screen>
    <StatusBar w={220} h={20} text="Games" bg="theme.panel" />
    <Menu x={8} y={27} w={204} h={105} focus={true} text="Game choices"
      items={['Comet Run', 'Pulse Path', 'Solitaire']} targets={['linnet.system.game-play', 'linnet.system.game-play', 'linnet.system.game-play']} />
    <Text x={8} y={139} w={204} h={31} text="Wheel: choose   Select: play" fg="theme.muted" />
  </Screen>);
}
