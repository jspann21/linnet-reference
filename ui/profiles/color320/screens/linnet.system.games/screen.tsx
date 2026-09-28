import { Screen, StatusBar, Menu, Text } from "@linnet/ui";
export default function Scene() {
  return (<Screen>
    <StatusBar w={320} h={28} text="Games" bg="theme.panel" deps={16} />
    <Menu x={12} y={39} w={296} h={128} focus={true} text="Game choices"
      items={['Comet Run', 'Pulse Path', 'Solitaire', 'Sudoku']} targets={['linnet.system.game-play', 'linnet.system.game-play', 'linnet.system.game-play', 'linnet.system.game-play']} />
    <Text x={16} y={169} w={288} h={24} text="Game description" fg="theme.foreground" deps={2} />
    <Text x={16} y={204} w={288} h={22} text="Wheel: choose   Select: play" fg="theme.muted" />
  </Screen>);
}
