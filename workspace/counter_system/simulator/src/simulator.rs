use crate::modules;
use sim_runtime::num_bigint::{BigInt, BigUint};
use sim_runtime::rand::seq::SliceRandom;
use sim_runtime::*;
use std::collections::HashMap;
use std::collections::VecDeque;
use std::sync::Arc;

pub struct Simulator {
  pub stamp: usize,
  pub request_stamp_map_table: HashMap<i64, usize>,
  pub cnt: Array<u32>,
  pub CounterInstance_triggered: bool,
  pub CounterInstance_event: VecDeque<usize>,
}

impl Simulator {
  pub fn new() -> Self {
    Simulator {
      stamp: 0,
      request_stamp_map_table: HashMap::new(),
      cnt: Array::new_with_ports(1, 1),
      CounterInstance_triggered: false,
      CounterInstance_event: VecDeque::new(),
    }
  }

  fn event_valid(&self, event: &VecDeque<usize>) -> bool {
    event.front().map_or(false, |x| *x <= self.stamp)
  }

  pub fn reset_downstream(&mut self) {
    self.CounterInstance_triggered = false;
  }

  pub fn tick_registers(&mut self) {
    self.cnt.tick(self.stamp);
  }

  pub fn reset_dram(&mut self) {}

  fn simulate_CounterInstance(&mut self) {
    if self.event_valid(&self.CounterInstance_event) {
      let succ = modules::CounterInstance::CounterInstance(self);
      if succ {
        self.CounterInstance_event.pop_front();
      } else {
      }
      self.CounterInstance_triggered = succ;
    } // close event condition
  } // close function
}

pub fn simulate() {
  let mut sim = Simulator::new();
  let simulators: Vec<fn(&mut Simulator)> = vec![Simulator::simulate_CounterInstance];
  let downstreams: Vec<fn(&mut Simulator)> = vec![];

  let mut idle_count = 0;
  for i in 1..=100 {
    sim.stamp = i * 100;
    sim.reset_downstream();

    for simulate in simulators.iter() {
      simulate(&mut sim);
    }

    for simulate in downstreams.iter() {
      simulate(&mut sim);
    }

    let any_module_triggered = sim.CounterInstance_triggered;

    // Handle idle threshold
    if !any_module_triggered {
      idle_count += 1;
      if idle_count >= 100 {
        println!("Simulation stopped due to reaching idle threshold of 100");
        break;
      }
    } else {
      idle_count = 0;
    }

    sim.stamp += 50;
    sim.tick_registers();
    sim.reset_dram();
    unsafe {
      // Tick all DRAM memory interfaces
    }
  }
}
