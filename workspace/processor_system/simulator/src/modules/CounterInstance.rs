use crate::simulator::Simulator;
use sim_runtime::num_bigint::{BigInt, BigUint};
use sim_runtime::*;
use std::ffi::c_void;

// Elaborating module CounterInstance
pub fn CounterInstance(sim: &mut Simulator) -> bool {
  let current = { sim.cnt.payload[false as usize].clone() };
  let new_value = { ValueCastTo::<u32>::cast(&current) + ValueCastTo::<u32>::cast(&1u32) };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:31
  print!("@line:{:<5} {:<10}: [CounterInstance]\t", line!(), cyclize(sim.stamp));
  println!("Counter value: {}", current,);
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:34
  {
    let stamp = sim.stamp - sim.stamp % 100 + 50;
    let write = ArrayWrite::new(stamp, false as usize, new_value.clone(), "CounterInstance");
    sim.cnt.write(0, write);
  };

  true
}
